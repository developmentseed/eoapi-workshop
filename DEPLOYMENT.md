# eoAPI deployment

## Requirements

- [uv](https://docs.astral.sh/uv/)
- [docker](https://docs.docker.com/get-started/get-docker/)
- [nvm](https://github.com/nvm-sh/nvm?tab=readme-ov-file#installing-and-updating)
- AWS credentials environment variables configured to point to an account.
- **Optional** a `config.yaml` file to override the default deployment settings defined in `config.py`.

## Installation

Install python dependencies with

```bash
uv sync --all-groups
```

And node dependencies with

```bash
nvm use
npm install
```

Verify that the `cdk` CLI is available. Since `aws-cdk` is installed as a local dependency, you can use the `npx` node package runner tool, that comes with `npm`.

```bash
npx cdk --version
```

## Deployment

Verify that the `cdk` CLI is available. Since `aws-cdk` is installed as a local dependency, you can use the `npx` node package runner tool, that comes with `npm`.

First, synthesize the app

```bash
uv run npx cdk synth --all
```

Then, deploy

```bash
uv run npx cdk deploy --all --require-approval never
```

## Set up for workshop

After deployment completes, you'll need to configure the workshop environment and share access credentials securely with participants.

### 1. Get Workshop Configuration Credentials

The CDK deployment creates a secure Lambda endpoint that provides database credentials and API endpoints to workshop participants. After deployment, retrieve the configuration values:

```bash
STACK_NAME=eoapiworkshop  # Your stack name from config.yaml

# Get the workshop config Lambda URL
WORKSHOP_CONFIG_URL=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='WorkshopConfigUrl'].OutputValue" \
  --output text)

# Get the workshop token
WORKSHOP_TOKEN=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='WorkshopToken'].OutputValue" \
  --output text)

echo "Workshop Config URL: $WORKSHOP_CONFIG_URL"
echo "Workshop Token: $WORKSHOP_TOKEN"
```

### 2. Update the `start` Script

Update the `start` file in the repository root with your Lambda URL and token:

```bash
# Edit the start script and replace:
WORKSHOP_CONFIG_URL="YOUR_LAMBDA_URL_HERE"  # Replace with $WORKSHOP_CONFIG_URL
WORKSHOP_TOKEN="YOUR_WORKSHOP_TOKEN_HERE"   # Replace with $WORKSHOP_TOKEN
```

Commit and push this change to your workshop repository. The 2i2c JupyterHub will use this script to automatically configure each user's environment with the necessary credentials and API endpoints.

**Security note:** The token in the `start` script acts as a workshop-wide password. Anyone with access to this repository can use it to get database credentials. After the workshop:

- Rotate the token by updating `workshop_token` in `config.yaml` and redeploying
- Or revoke access by deleting the workshop config Lambda function

### 3. Test the Configuration Endpoint

You can test that the endpoint works correctly:

```bash
curl -H "Authorization: Bearer $WORKSHOP_TOKEN" $WORKSHOP_CONFIG_URL | jq .
```

This should return JSON with all the configuration values:

```json
{
  "pghost": "...",
  "pgport": "5432",
  "pgdatabase": "postgis",
  "pguser": "...",
  "pgpassword": "...",
  "stac_api_endpoint": "https://...",
  "titiler_pgstac_api_endpoint": "https://...",
  "tipg_api_endpoint": "https://..."
}
```

### 4. Load the Level III Ecoregions of North America features into a postgis table

Start by querying the AWS CloudFormation Stack to get the pgstac database credentials

```bash
PGSTAC_STACK=eoapiworkshop
PGSTAC_SECRET_ARN=$(aws cloudformation describe-stacks --stack-name $PGSTAC_STACK --query "Stacks[0].Outputs[?OutputKey=='PgstacSecret'].OutputValue" --output text)
PGSTAC_SECRET_VALUE=$(aws secretsmanager get-secret-value \
  --secret-id "$PGSTAC_SECRET_ARN" \
  --query "SecretString" \
  --output text) 

export PGHOST=$(echo "$PGSTAC_SECRET_VALUE" | jq -r '.host')
export PGPORT=$(echo "$PGSTAC_SECRET_VALUE" | jq -r '.port')
export PGDATABASE=$(echo "$PGSTAC_SECRET_VALUE" | jq -r '.dbname')
export PGUSER=$(echo "$PGSTAC_SECRET_VALUE" | jq -r '.username')
export PGPASSWORD=$(echo "$PGSTAC_SECRET_VALUE" | jq -r '.password')
```

Then use psql to create a new schema (`features`) and make sure there is a spot for the new table:

```bash
psql -c "CREATE SCHEMA features;"
psql -c "DROP TABLE IF EXISTS features.ecoregions;"

```

Use the `ogr2ogr` (via GDAL docker image) to write the ecoregion features from a zipped shapefile on the web directly to our PostGIS database table:

```bash
docker pull ghcr.io/osgeo/gdal:alpine-small-latest
 gdalinfo $PWD/my.tif

docker run --rm ghcr.io/osgeo/gdal:alpine-small-latest ogr2ogr -f "PostgreSQL" \
  PG:"postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}" \
  /vsizip/vsicurl/https://dmap-prod-oms-edc.s3.us-east-1.amazonaws.com/ORD/Ecoregions/cec_na/NA_CEC_Eco_Level3.zip/NA_CEC_Eco_Level3.shp \
  -nln features.ecoregions \
  -lco GEOMETRY_NAME=geom \
  -lco FID=id \
  -lco PRECISION=NO \
  -nlt PROMOTE_TO_MULTI \
  -t_srs EPSG:4326
```
