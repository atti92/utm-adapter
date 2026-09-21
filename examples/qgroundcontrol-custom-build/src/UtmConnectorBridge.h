#pragma once

#include <QtCore/QJsonObject>
#include <QtCore/QObject>
#include <QtCore/QString>
#include <QtCore/QUrl>

class QNetworkAccessManager;
class QNetworkReply;

/// Small QML-facing client for the connector's operator API.
///
/// This bridge deliberately has no MAVLink or vehicle-control operations. It
/// serializes the plan already owned by QGroundControl and sends UTM mission
/// and operation-intent requests over HTTP.
class UtmConnectorBridge : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString lastMessage READ lastMessage NOTIFY lastMessageChanged)
    Q_PROPERTY(QString lastError READ lastError NOTIFY lastErrorChanged)

public:
    explicit UtmConnectorBridge(QObject *parent = nullptr);

    bool busy() const { return _busy; }
    QString lastMessage() const { return _lastMessage; }
    QString lastError() const { return _lastError; }

    Q_INVOKABLE QString newOperationId() const;
    Q_INVOKABLE void submitCurrentPlan(const QString &connectorBaseUrl,
                                       QObject *planController,
                                       const QString &vehicleId,
                                       const QString &validFrom,
                                       const QString &validUntil,
                                       double corridorRadiusM);
    Q_INVOKABLE void sendOperationIntent(const QString &connectorBaseUrl,
                                         const QString &vehicleId,
                                         const QString &operationId,
                                         const QString &command);

signals:
    void busyChanged();
    void lastMessageChanged();
    void lastErrorChanged();
    void requestFinished(bool success, const QString &message);

private:
    void postJson(const QUrl &url, const QJsonObject &body, const QString &action);
    void setBusy(bool busy);
    void setMessage(const QString &message);
    void setError(const QString &message);
    static QUrl endpoint(const QString &connectorBaseUrl, const QString &path);

    QNetworkAccessManager *_network = nullptr;
    bool _busy = false;
    QString _lastMessage;
    QString _lastError;
};
