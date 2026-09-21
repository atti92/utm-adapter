#include "UtmConnectorBridge.h"

#include "PlanMasterController.h"

#include <QtCore/QJsonDocument>
#include <QtCore/QJsonObject>
#include <QtCore/QUuid>
#include <QtCore/QUrlQuery>
#include <QtNetwork/QNetworkAccessManager>
#include <QtNetwork/QNetworkReply>
#include <QtNetwork/QNetworkRequest>

namespace {

QString normalizedBaseUrl(const QString &baseUrl)
{
    QString normalized = baseUrl.trimmed();
    while (normalized.endsWith('/')) {
        normalized.chop(1);
    }
    return normalized;
}

QString responseMessage(QNetworkReply *reply, const QString &fallback)
{
    const QByteArray response = reply->readAll();
    const QJsonDocument document = QJsonDocument::fromJson(response);
    if (document.isObject()) {
        const QJsonObject object = document.object();
        const QJsonValue detail = object.value(QStringLiteral("detail"));
        if (detail.isString()) {
            return detail.toString();
        }
        if (object.value(QStringLiteral("operation_id")).isString()) {
            return fallback + QStringLiteral(" (operation ")
                + object.value(QStringLiteral("operation_id")).toString() + QStringLiteral(")");
        }
        if (object.value(QStringLiteral("mission_hash")).isString()) {
            return fallback + QStringLiteral(" (mission saved)");
        }
    }
    return fallback;
}

} // namespace

UtmConnectorBridge::UtmConnectorBridge(QObject *parent)
    : QObject(parent)
    , _network(new QNetworkAccessManager(this))
{
}

QString UtmConnectorBridge::newOperationId() const
{
    return QUuid::createUuid().toString(QUuid::WithoutBraces);
}

QUrl UtmConnectorBridge::endpoint(const QString &connectorBaseUrl, const QString &path)
{
    return QUrl(normalizedBaseUrl(connectorBaseUrl) + path);
}

void UtmConnectorBridge::setBusy(bool busy)
{
    if (_busy == busy) {
        return;
    }
    _busy = busy;
    emit busyChanged();
}

void UtmConnectorBridge::setMessage(const QString &message)
{
    if (_lastMessage == message) {
        return;
    }
    _lastMessage = message;
    emit lastMessageChanged();
}

void UtmConnectorBridge::setError(const QString &message)
{
    if (_lastError == message) {
        return;
    }
    _lastError = message;
    emit lastErrorChanged();
}

void UtmConnectorBridge::postJson(const QUrl &url, const QJsonObject &body, const QString &action)
{
    if (_busy) {
        const QString message = QStringLiteral("Another UTM request is still in progress.");
        setError(message);
        emit requestFinished(false, message);
        return;
    }

    if (!url.isValid() || url.scheme().isEmpty() || url.host().isEmpty()) {
        const QString message = QStringLiteral("The connector URL is invalid.");
        setError(message);
        emit requestFinished(false, message);
        return;
    }

    setBusy(true);
    setError(QString());
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    QNetworkReply *reply = _network->post(request, QJsonDocument(body).toJson(QJsonDocument::Compact));
    connect(reply, &QNetworkReply::finished, this, [this, reply, action]() {
        const int statusCode = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const bool success = reply->error() == QNetworkReply::NoError && statusCode >= 200 && statusCode < 300;
        QString message;
        if (success) {
            message = responseMessage(reply, action + QStringLiteral(" completed"));
            setMessage(message);
        } else {
            message = responseMessage(reply, action + QStringLiteral(" failed"));
            if (reply->error() != QNetworkReply::NoError && statusCode == 0) {
                message = action + QStringLiteral(": ") + reply->errorString();
            }
            setError(message);
        }
        setBusy(false);
        emit requestFinished(success, message);
        reply->deleteLater();
    });
}

void UtmConnectorBridge::submitCurrentPlan(const QString &connectorBaseUrl,
                                           QObject *planController,
                                           const QString &vehicleId,
                                           const QString &validFrom,
                                           const QString &validUntil,
                                           double corridorRadiusM)
{
    auto *controller = qobject_cast<PlanMasterController *>(planController);
    if (!controller || !controller->containsItems()) {
        const QString message = QStringLiteral("Create or load a QGroundControl mission first.");
        setError(message);
        emit requestFinished(false, message);
        return;
    }
    if (vehicleId.trimmed().isEmpty() || validFrom.trimmed().isEmpty() || validUntil.trimmed().isEmpty()) {
        const QString message = QStringLiteral("Vehicle and future UTM validity times are required.");
        setError(message);
        emit requestFinished(false, message);
        return;
    }
    if (!(corridorRadiusM > 0.0)) {
        const QString message = QStringLiteral("The UTM corridor must be greater than zero.");
        setError(message);
        emit requestFinished(false, message);
        return;
    }

    const QJsonDocument plan = controller->saveToJson();
    if (!plan.isObject() || plan.object().isEmpty()) {
        const QString message = QStringLiteral("QGroundControl could not serialize the current mission.");
        setError(message);
        emit requestFinished(false, message);
        return;
    }

    QJsonObject body{
        {QStringLiteral("valid_from"), validFrom},
        {QStringLiteral("valid_until"), validUntil},
        {QStringLiteral("corridor_radius_m"), corridorRadiusM},
        {QStringLiteral("plan"), plan.object()},
    };
    const QString encodedVehicle = QString::fromUtf8(QUrl::toPercentEncoding(vehicleId.trimmed()));
    postJson(endpoint(connectorBaseUrl,
                      QStringLiteral("/v1/missions/") + encodedVehicle + QStringLiteral("/qgroundcontrol")),
             body,
             QStringLiteral("Mission upload"));
}

void UtmConnectorBridge::sendOperationIntent(const QString &connectorBaseUrl,
                                             const QString &vehicleId,
                                             const QString &operationId,
                                             const QString &command)
{
    if (vehicleId.trimmed().isEmpty() || operationId.trimmed().isEmpty() || command.trimmed().isEmpty()) {
        const QString message = QStringLiteral("Vehicle, operation, and command are required.");
        setError(message);
        emit requestFinished(false, message);
        return;
    }

    QJsonObject body{
        {QStringLiteral("schema_version"), QStringLiteral("1.0")},
        {QStringLiteral("operation_id"), operationId.trimmed()},
        {QStringLiteral("command"), command.trimmed()},
    };
    QUrl url = endpoint(connectorBaseUrl, QStringLiteral("/v1/operator-intents"));
    QUrlQuery query;
    query.addQueryItem(QStringLiteral("vehicle_id"), vehicleId.trimmed());
    url.setQuery(query);
    postJson(url, body, command.trimmed());
}
