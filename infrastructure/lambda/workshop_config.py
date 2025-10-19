"""
Lambda function to provide workshop configuration including database credentials
and API endpoints.

This function:
1. Validates bearer token authorization
2. Fetches database credentials from AWS Secrets Manager
3. Returns all environment variables needed for workshop notebooks
"""

import json
import os

import boto3

# Initialize AWS clients
secrets_client = boto3.client("secretsmanager")

# Get configuration from environment
PGSTAC_SECRET_ARN = os.environ["PGSTAC_SECRET_ARN"]
WORKSHOP_TOKEN = os.environ["WORKSHOP_TOKEN"]
STAC_API_ENDPOINT = os.environ.get("STAC_API_ENDPOINT", "")
TITILER_PGSTAC_API_ENDPOINT = os.environ.get("TITILER_PGSTAC_API_ENDPOINT", "")
TIPG_API_ENDPOINT = os.environ.get("TIPG_API_ENDPOINT", "")


def handler(event, context):
    """
    Lambda handler to return workshop configuration.

    Expects Authorization header with Bearer token.
    Returns JSON with database credentials and API endpoints.
    """

    # Extract authorization header
    headers = event.get("headers", {})
    # Handle case-insensitive header lookup
    auth_header = None
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth_header = value
            break

    # Validate bearer token
    if not auth_header or not auth_header.startswith("Bearer "):
        return {
            "statusCode": 401,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Missing or invalid Authorization header"}),
        }

    token = auth_header.replace("Bearer ", "")
    if token != WORKSHOP_TOKEN:
        return {
            "statusCode": 401,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Invalid token"}),
        }

    try:
        # Fetch database credentials from Secrets Manager
        secret_response = secrets_client.get_secret_value(SecretId=PGSTAC_SECRET_ARN)
        secret_data = json.loads(secret_response["SecretString"])

        # Build response with all environment variables
        config = {
            "pghost": secret_data.get("host"),
            "pgport": str(secret_data.get("port")),
            "pgdatabase": secret_data.get("dbname"),
            "pguser": secret_data.get("username"),
            "pgpassword": secret_data.get("password"),
            "stac_api_endpoint": STAC_API_ENDPOINT,
            "titiler_pgstac_api_endpoint": TITILER_PGSTAC_API_ENDPOINT,
            "tipg_api_endpoint": TIPG_API_ENDPOINT,
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(config),
        }

    except Exception as e:
        print(f"Error fetching configuration: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Failed to retrieve configuration"}),
        }
