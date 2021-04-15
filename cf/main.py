#!/usr/bin/env python3
import base64
import json
import os

import requests
from google.cloud import secretmanager, securitycenter_v1

PREFIX = "https://console.cloud.google.com/security/command-center/findings"


def get_azure_app_secret():
    client = secretmanager.SecretManagerServiceClient()
    secret_name = client.secret_version_path(
        os.environ["PROJECT_ID"], "azure-app-secret", "latest"
    )
    return client.access_secret_version(
        request={"name": secret_name}
    ).payload.data.decode("UTF-8")


def get_azure_token():
    resp = requests.post(
        f'https://login.microsoftonline.com/{os.environ["TENANT_ID"]}/oauth2/v2.0/token',
        data={
            "client_id": os.environ["CLIENT_ID"],
            "scope": "https://graph.microsoft.com/.default",
            "client_secret": get_azure_app_secret(),
            "grant_type": "client_credentials",
        },
    )

    return resp.json()


def get_finding_detail_page_link(finding_name):
    """Constructs a direct link to the finding detail page."""
    org_id = finding_name.split("/")[1]
    return f"{PREFIX}?organizationId={org_id}&resourceId={finding_name}"


def get_asset(org_id, resource_name):
    """Retrieves the asset corresponding to `resource_name` from SCC."""
    client = securitycenter_v1.SecurityCenterClient()
    maybe_asset = list(
        client.list_assets(
            securitycenter_v1.ListAssetsRequest(
                parent=f"organizations/{org_id}",
                filter=f'security_center_properties.resource_name = "{resource_name}"',
            )
        )
    )
    if len(maybe_asset) == 1:
        return maybe_asset[0].asset
    return securitycenter_v1.Asset()


def send_email_notification(event, context):
    """Email the finding notification."""
    pubsub_message = base64.b64decode(event["data"]).decode("utf-8")
    finding = json.loads(pubsub_message)["finding"]
    asset = get_asset(finding["parent"].split("/")[1], finding["resourceName"])

    token = get_azure_token()
    subject = f'New {finding["severity"]} severity finding: {finding["category"]}'
    content = "\n".join(
        [
            f'Severity: {finding["severity"]}',
            f"Asset: {asset.security_center_properties.resource_display_name}",
            f'SCC Category: {finding["category"]}',
            f"Project: {asset.security_center_properties.resource_project_display_name}",
            f'First observed: {finding["createTime"]}',
            f'Last observed: {finding["eventTime"]}',
            f'Link to finding: {get_finding_detail_page_link(finding["name"])}',
        ]
    )

    requests.post(
        f'https://graph.microsoft.com/v1.0/users/{os.environ["USER_ID"]}/sendMail',
        json={
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": content},
                "toRecipients": [
                    {"emailAddress": {"address": os.environ["RECIPIENT"]}}
                ],
            }
        },
        headers={"Authorization": f'{token["token_type"]} {token["access_token"]}'},
    ).raise_for_status()
