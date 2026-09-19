// UTM Connector Mission Planner plugin.
//
// Mission Planner remains the vehicle-control application. This plugin only
// reads the mission currently visible in Flight Planner and calls the local
// UTM Connector HTTP API. It never writes to Host.comPort and never sends a
// vehicle-control MAVLink command.

using MissionPlanner;
using MissionPlanner.Controls;
using MissionPlanner.Plugin;
using MissionPlanner.Utilities;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;

public class UtmConnectorPlugin : Plugin
{
    private const string DefaultConnectorBaseUrl = "http://127.0.0.1:8000";
    private const string DefaultVehicleId = "sitl-1";

    private ToolStripMenuItem connectorMenu;
    private ToolStripMenuItem statusMenu;
    private string connectorBaseUrl;
    private string vehicleId;
    private string operationId;

    public override string Name { get { return "UTM Connector"; } }
    public override string Version { get { return "2.0"; } }
    public override string Author { get { return "utm-adapter"; } }

    public override bool Init()
    {
        connectorBaseUrl = Settings.Instance.GetString("utm_connector_url", DefaultConnectorBaseUrl)
            .TrimEnd('/');
        vehicleId = Settings.Instance.GetString("utm_connector_vehicle_id", DefaultVehicleId);
        loopratehz = 0;
        return true;
    }

    public override bool Loaded()
    {
        connectorMenu = new ToolStripMenuItem("UTM Connector");

        var configure = new ToolStripMenuItem("Configure connector...");
        configure.Click += delegate { ConfigureConnector(); };
        connectorMenu.DropDownItems.Add(configure);

        var openConsole = new ToolStripMenuItem("Open operator console");
        openConsole.Click += delegate { OpenUrl(connectorBaseUrl + "/ui/"); };
        connectorMenu.DropDownItems.Add(openConsole);

        var checkConnector = new ToolStripMenuItem("Check connector");
        checkConnector.Click += delegate { CheckConnector(); };
        connectorMenu.DropDownItems.Add(checkConnector);

        connectorMenu.DropDownItems.Add(new ToolStripSeparator());

        var syncMission = new ToolStripMenuItem("Sync current mission");
        syncMission.Click += delegate { SyncCurrentMission(); };
        connectorMenu.DropDownItems.Add(syncMission);

        var submitOperation = new ToolStripMenuItem("Submit operation");
        submitOperation.Click += delegate { SubmitOperation(); };
        connectorMenu.DropDownItems.Add(submitOperation);

        var startOperation = new ToolStripMenuItem("Start operation");
        startOperation.Click += delegate { ApplyOperation("START_OPERATION", "Starting operation"); };
        connectorMenu.DropDownItems.Add(startOperation);

        var cancelOperation = new ToolStripMenuItem("Cancel operation");
        cancelOperation.Click += delegate { ApplyOperation("CANCEL_OPERATION", "Cancelling operation"); };
        connectorMenu.DropDownItems.Add(cancelOperation);

        var completeOperation = new ToolStripMenuItem("Complete operation");
        completeOperation.Click += delegate { ApplyOperation("COMPLETE_OPERATION", "Completing operation"); };
        connectorMenu.DropDownItems.Add(completeOperation);

        connectorMenu.DropDownItems.Add(new ToolStripSeparator());
        statusMenu = new ToolStripMenuItem(StatusText("not checked")) { Enabled = false };
        connectorMenu.DropDownItems.Add(statusMenu);

        // FDMenuMap is available in Mission Planner's PluginHost and keeps the
        // integration visible from the normal Flight Data workflow.
        Host.FDMenuMap.Items.Add(connectorMenu);
        return true;
    }

    public override bool Loop()
    {
        // All connector calls are explicit operator actions. There is no
        // background polling and no competing MAVLink command path.
        return true;
    }

    public override bool Exit()
    {
        if (connectorMenu != null && Host.FDMenuMap.Items.Contains(connectorMenu))
        {
            Host.FDMenuMap.Items.Remove(connectorMenu);
        }

        return true;
    }

    private void ConfigureConnector()
    {
        var url = connectorBaseUrl;
        if (InputBox.Show("Connector URL", "UTM Connector URL", ref url) != DialogResult.OK)
            return;

        var selectedVehicleId = vehicleId;
        if (InputBox.Show("Vehicle ID", "Connector vehicle ID", ref selectedVehicleId) != DialogResult.OK)
            return;

        url = url.Trim().TrimEnd('/');
        selectedVehicleId = selectedVehicleId.Trim();
        if (url.Length == 0 || selectedVehicleId.Length == 0)
        {
            ShowMessage("Connector URL and vehicle ID are required.");
            return;
        }

        connectorBaseUrl = url;
        vehicleId = selectedVehicleId;
        Settings.Instance["utm_connector_url"] = connectorBaseUrl;
        Settings.Instance["utm_connector_vehicle_id"] = vehicleId;
        SetStatus("configured for " + vehicleId);
    }

    private void CheckConnector()
    {
        SetStatus("checking...");
        RunRequest("Checking connector", delegate
        {
            SendJson("GET", "/v1/health", null);
            return "online for " + vehicleId;
        });
    }

    private void SyncCurrentMission()
    {
        string missionText;
        try
        {
            missionText = BuildMissionPlannerWpl();
        }
        catch (Exception ex)
        {
            ShowMessage("Could not read the current Mission Planner mission:\r\n" + ex.Message);
            return;
        }

        var validFrom = DateTime.UtcNow.AddMinutes(1).ToString("o", CultureInfo.InvariantCulture);
        var validUntil = DateTime.UtcNow.AddHours(2).ToString("o", CultureInfo.InvariantCulture);
        var body = "{\"valid_from\":\"" + JsonEscape(validFrom) +
                   "\",\"valid_until\":\"" + JsonEscape(validUntil) +
                   "\",\"corridor_radius_m\":30,\"text\":\"" +
                   JsonEscape(missionText) + "\"}";

        RunRequest("Syncing mission", delegate
        {
            SendJson("PUT", "/v1/missions/" + Uri.EscapeDataString(vehicleId) + "/mission-planner", body);
            return "mission synced for " + vehicleId;
        });
    }

    private void SubmitOperation()
    {
        var newOperationId = Guid.NewGuid().ToString();
        var body = "{\"schema_version\":\"1.0\",\"operation_id\":\"" +
                   newOperationId + "\",\"command\":\"SUBMIT_OPERATION\"}";

        RunRequest("Submitting operation", delegate
        {
            var response = SendJson("POST", "/v1/operator-intents?vehicle_id=" +
                                    Uri.EscapeDataString(vehicleId), body);
            operationId = ReadJsonString(response, "operation_id", newOperationId);
            return "submitted " + operationId;
        });
    }

    private void ApplyOperation(string command, string description)
    {
        if (String.IsNullOrEmpty(operationId))
        {
            ShowMessage("Submit an operation first, then retry this action.");
            return;
        }

        var body = "{\"schema_version\":\"1.0\",\"operation_id\":\"" +
                   operationId + "\",\"command\":\"" + command + "\"}";
        RunRequest(description, delegate
        {
            SendJson("POST", "/v1/operator-intents?vehicle_id=" +
                     Uri.EscapeDataString(vehicleId), body);
            return command.Replace("_", " ").ToLowerInvariant() + " complete";
        });
    }

    private string BuildMissionPlannerWpl()
    {
        var grid = Host.MainForm.FlightPlanner.Controls.Find("Commands", true)
            .FirstOrDefault() as DataGridView;
        if (grid == null)
            throw new InvalidOperationException("Flight Planner mission grid is not available.");

        var home = Host.cs.HomeLocation;
        if (home.Lat == 0 && home.Lng == 0)
            home = Host.cs.PlannedHomeLocation;

        var lines = new List<string> { "QGC WPL 110" };
        lines.Add(WplLine(0, 1, 0, 16, 0, 0, 0, 0, home.Lat, home.Lng, home.Alt));

        var sequence = 1;
        foreach (DataGridViewRow row in grid.Rows)
        {
            if (row.IsNewRow)
                continue;

            var command = ParseEnumValue<MAVLink.MAV_CMD>(row.Cells["Command"].Value, "command");
            if (command != MAVLink.MAV_CMD.WAYPOINT && command != MAVLink.MAV_CMD.TAKEOFF)
            {
                throw new InvalidOperationException(
                    "The connector currently accepts only WAYPOINT and TAKEOFF items; " + command + " is present.");
            }

            var frame = ParseEnumValue<MAVLink.MAV_FRAME>(row.Cells["Frame"].Value, "frame");
            lines.Add(WplLine(
                sequence++,
                0,
                Convert.ToInt32(frame),
                Convert.ToInt32(command),
                CellDouble(row, "Param1"),
                CellDouble(row, "Param2"),
                CellDouble(row, "Param3"),
                CellDouble(row, "Param4"),
                CellDouble(row, "Lat"),
                CellDouble(row, "Lon"),
                CellDouble(row, "Alt")));
        }

        if (sequence < 3)
            throw new InvalidOperationException("At least two navigable mission items are required.");
        return String.Join("\n", lines) + "\n";
    }

    private static string WplLine(int sequence, int current, int frame, int command,
        double p1, double p2, double p3, double p4, double latitude, double longitude, double altitude)
    {
        return String.Join("\t", new[]
        {
            sequence.ToString(CultureInfo.InvariantCulture),
            current.ToString(CultureInfo.InvariantCulture),
            frame.ToString(CultureInfo.InvariantCulture),
            command.ToString(CultureInfo.InvariantCulture),
            p1.ToString("0.########", CultureInfo.InvariantCulture),
            p2.ToString("0.########", CultureInfo.InvariantCulture),
            p3.ToString("0.########", CultureInfo.InvariantCulture),
            p4.ToString("0.########", CultureInfo.InvariantCulture),
            latitude.ToString("0.##########", CultureInfo.InvariantCulture),
            longitude.ToString("0.##########", CultureInfo.InvariantCulture),
            altitude.ToString("0.########", CultureInfo.InvariantCulture),
            "1"
        });
    }

    private static double CellDouble(DataGridViewRow row, string name)
    {
        var value = row.Cells[name].Value;
        if (value == null || String.IsNullOrWhiteSpace(value.ToString()))
            return 0;
        double result;
        if (Double.TryParse(value.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out result))
            return result;
        if (Double.TryParse(value.ToString(), NumberStyles.Float, CultureInfo.CurrentCulture, out result))
            return result;
        throw new InvalidOperationException("Mission field " + name + " is not numeric.");
    }

    private static T ParseEnumValue<T>(object value, string field) where T : struct
    {
        if (value == null)
            throw new InvalidOperationException("Mission field " + field + " is empty.");

        try
        {
            if (value is T)
                return (T)value;
            int numeric;
            if (Int32.TryParse(value.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out numeric))
                return (T)Enum.ToObject(typeof(T), numeric);
            return (T)Enum.Parse(typeof(T), value.ToString(), true);
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException("Mission field " + field + " is invalid: " + value, ex);
        }
    }

    private string SendJson(string method, string path, string body)
    {
        var request = (HttpWebRequest)WebRequest.Create(connectorBaseUrl + path);
        request.Method = method;
        request.Timeout = 10000;
        request.ReadWriteTimeout = 10000;
        request.Accept = "application/json";
        if (body != null)
        {
            var bytes = Encoding.UTF8.GetBytes(body);
            request.ContentType = "application/json";
            request.ContentLength = bytes.Length;
            using (var stream = request.GetRequestStream())
                stream.Write(bytes, 0, bytes.Length);
        }

        try
        {
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream()))
                return reader.ReadToEnd();
        }
        catch (WebException ex)
        {
            var response = ex.Response as HttpWebResponse;
            if (response != null)
            {
                using (response)
                using (var reader = new StreamReader(response.GetResponseStream()))
                    throw new InvalidOperationException("HTTP " + (int)response.StatusCode + ": " + reader.ReadToEnd());
            }
            throw;
        }
    }

    private void RunRequest(string description, Func<string> action)
    {
        SetStatus(description.ToLowerInvariant() + "...");
        Task.Run(delegate
        {
            try
            {
                var result = action();
                SetStatus(result);
                ShowMessage(result + ".");
            }
            catch (Exception ex)
            {
                SetStatus("error");
                ShowMessage(description + " failed:\r\n" + ex.Message);
            }
        });
    }

    private static string ReadJsonString(string payload, string name, string fallback)
    {
        var match = Regex.Match(payload ?? "", "\\\"" + Regex.Escape(name) + "\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"");
        return match.Success ? match.Groups[1].Value : fallback;
    }

    private static string JsonEscape(string value)
    {
        return value.Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\t", "\\t")
            .Replace("\r", "\\r")
            .Replace("\n", "\\n");
    }

    private void OpenUrl(string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = url,
                UseShellExecute = true
            });
        }
        catch (Exception ex)
        {
            ShowMessage("Could not open the UTM Connector console: " + ex.Message);
        }
    }

    private string StatusText(string value)
    {
        return "Status: " + value;
    }

    private void SetStatus(string status)
    {
        if (statusMenu == null || Host.MainForm == null || Host.MainForm.IsDisposed)
            return;

        try
        {
            Host.MainForm.BeginInvoke((Action)delegate
            {
                if (statusMenu != null)
                    statusMenu.Text = StatusText(status);
            });
        }
        catch
        {
            // Mission Planner may be shutting down while a request finishes.
        }
    }

    private void ShowMessage(string message)
    {
        if (Host.MainForm == null || Host.MainForm.IsDisposed)
            return;

        try
        {
            Host.MainForm.BeginInvoke((Action)delegate
            {
                MessageBox.Show(Host.MainForm, message, Name, MessageBoxButtons.OK, MessageBoxIcon.Information);
            });
        }
        catch
        {
            // Mission Planner may be shutting down.
        }
    }
}
