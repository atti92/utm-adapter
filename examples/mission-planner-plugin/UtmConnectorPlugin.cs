// UTM Connector Mission Planner plugin.
//
// Mission Planner loads C# source files placed in its plugins directory. This
// deliberately keeps the GCS integration thin: Mission Planner remains the
// vehicle-control application and the connector owns UTM declarations,
// telemetry publication, and the operator workflow in its local web console.

using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading.Tasks;
using System.Windows.Forms;
using MissionPlanner.Plugin;

public class UtmConnectorPlugin : Plugin
{
    private const string ConnectorBaseUrl = "http://127.0.0.1:8000";
    private const string HealthUrl = ConnectorBaseUrl + "/v1/health";
    private const string ConsoleUrl = ConnectorBaseUrl + "/ui/";

    private ToolStripMenuItem connectorMenu;
    private ToolStripMenuItem statusMenu;

    public override string Name { get { return "UTM Connector"; } }
    public override string Version { get { return "1.0"; } }
    public override string Author { get { return "utm-adapter"; } }

    public override bool Init()
    {
        // The plugin is intentionally non-commanding. It does not write to
        // Host.comPort and does not send MAVLink vehicle-control messages.
        loopratehz = 0;
        return true;
    }

    public override bool Loaded()
    {
        connectorMenu = new ToolStripMenuItem("UTM Connector");

        var openConsole = new ToolStripMenuItem("Open operator console");
        openConsole.Click += delegate { OpenUrl(ConsoleUrl); };
        connectorMenu.DropDownItems.Add(openConsole);

        var checkConnector = new ToolStripMenuItem("Check connector");
        checkConnector.Click += delegate { CheckConnector(); };
        connectorMenu.DropDownItems.Add(checkConnector);

        statusMenu = new ToolStripMenuItem("Status: not checked") { Enabled = false };
        connectorMenu.DropDownItems.Add(statusMenu);

        // FDMenuMap is available in Mission Planner's PluginHost and keeps the
        // integration visible from the normal Flight Data workflow.
        Host.FDMenuMap.Items.Add(connectorMenu);
        return true;
    }

    public override bool Loop()
    {
        // No polling is needed. The operator can request an explicit health
        // check, which avoids background network traffic from the GCS plugin.
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

    private void CheckConnector()
    {
        SetStatus("checking...");

        Task.Run(delegate
        {
            try
            {
                var request = (HttpWebRequest)WebRequest.Create(HealthUrl);
                request.Method = "GET";
                request.Timeout = 2000;
                using (var response = (HttpWebResponse)request.GetResponse())
                {
                    return response.StatusCode == HttpStatusCode.OK
                        ? "online"
                        : "HTTP " + (int)response.StatusCode;
                }
            }
            catch (Exception ex)
            {
                return "offline: " + ex.Message;
            }
        }).ContinueWith(task => SetStatus(task.Result));
    }

    private void SetStatus(string status)
    {
        if (statusMenu == null || Host.MainForm == null || Host.MainForm.IsDisposed)
        {
            return;
        }

        try
        {
            Host.MainForm.BeginInvoke((Action)delegate
            {
                if (statusMenu != null)
                {
                    statusMenu.Text = "Status: " + status;
                }
            });
        }
        catch
        {
            // Mission Planner may be shutting down while a health check
            // finishes; the result is not important during shutdown.
        }
    }

    private void ShowMessage(string message)
    {
        if (Host.MainForm == null || Host.MainForm.IsDisposed)
        {
            return;
        }

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
