# eoAPI deployment

## Deployment Strategy

This workshop uses a **single AWS stack, multiple workshop instances** approach:

- **One AWS Deployment**: Deploy the eoAPI infrastructure (database, APIs, Lambda functions) once to AWS. This stack is persistent and serves all workshop variants.
- **Multiple Workshop Variants**: Create different branches or tags with updated notebook content for different workshops. Each workshop points to the same AWS backend but can have customized learning materials.
- **Flexible Content Updates**: Update workshop notebooks without redeploying AWS infrastructure. Simply create a new branch, update the Binder badge link in the README, and share the new link with participants.

This approach minimizes AWS costs and deployment complexity while maximizing flexibility for workshop organizers.

## When to Redeploy the Stack

You only need to redeploy the AWS stack in these scenarios:

1. **Initial Deployment**: First time setting up the workshop infrastructure
2. **Stack Teardown Recovery**: The stack was destroyed (e.g., for cost savings) and needs to be recreated
3. **Token Rotation**: Updating the `WORKSHOP_TOKEN` for security purposes after a workshop ends
4. **New Infrastructure Arrangement**: Changes to VPC, networking, or other infrastructure configuration

**To rotate the workshop token:**
1. Go to GitHub Settings → Secrets and variables → Actions → Variables
2. Update the `WORKSHOP_TOKEN` variable with a new value
3. Run the CDK Deploy workflow from the Actions tab

## Updating Workshop Content

For new workshops with different or updated notebook materials:

1. **Create a Branch or Tag**:
   ```bash
   git checkout -b workshop-name-2025
   # Make your notebook changes
   git commit -am "Update notebooks for workshop-name-2025"
   git push origin workshop-name-2025
   ```

2. **Update the Binder Link**:
   Edit the Binder badge in `README.md` to point to your new branch:
   ```markdown
   [![Binder](https://binder.opensci.2i2c.cloud/badge_logo.svg)](https://binder.opensci.2i2c.cloud/v2/gh/developmentseed/eoapi-workshop/workshop-name-2025?urlpath=%2Fdoc%2Ftree%2Fdocs%2F00-introduction.ipynb)
   ```

3. **Share the Updated Link**: Participants clicking this link will get a JupyterHub instance with your updated notebooks, connected to the same AWS backend.

**Benefits of this approach:**
- No AWS redeployment needed
- No additional infrastructure costs
- Fast iteration on workshop content
- Different workshops can run concurrently with the same backend

## AWS Stack Deployment

### Deployment via GitHub Actions (Recommended)

The easiest way to deploy is using the GitHub Actions workflow, which automatically handles all dependencies and AWS authentication.

### Prerequisites

1. **GitHub Environment Configuration**

   Create a `dev` environment in your GitHub repository (Settings → Environments → New environment).

2. **Configure GitHub Variables**

   In Settings → Secrets and variables → Actions → Variables tab, add:

   - `DEPLOY_IAM_ROLE_ARN` - ARN of the IAM role for GitHub Actions to assume
   - `AWS_REGION` - AWS region (e.g., `us-east-1`)
   - `PROJECT_ID` - Project identifier (e.g., `eoapi-workshop-dev`)
   - `VPC_ID` - **Required** - VPC ID where resources will be deployed
   - `HOSTED_ZONE_ID` - **Required** - Route53 hosted zone ID for `eoapi.dev` domain
   - `CERTIFICATE_ARN` - **Required** - ACM certificate ARN for `*.eoapi.dev` wildcard certificate
   - `WORKSHOP_TOKEN` - Bearer token for workshop config (optional, auto-generated if not provided)
   - `PGSTAC_VERSION` - pgstac version (optional, defaults to `0.9.8`)

3. **IAM Role Setup**

   Your IAM role must:
   - Have a trust relationship allowing GitHub Actions OIDC provider
   - Have permissions for CDK deployment (CloudFormation, Lambda, RDS, VPC, EC2, Secrets Manager, etc.)

### Deploy

1. Go to your repository's **Actions** tab
2. Select the **CDK Deploy** workflow
3. Click **Run workflow**
4. Enter the branch or tag you want to deploy (defaults to `main`)
5. Enter the deployment environment name (defaults to `dev`)
6. Click **Run workflow**

The workflow will:
- Check out your specified branch/tag
- Install all dependencies (Python via uv, Node.js)
- Configure AWS credentials via OIDC
- Synthesize the CDK stack
- Deploy to AWS

### Destroy

To tear down the AWS stack (e.g., for cost savings after a workshop ends):

1. Go to your repository's **Actions** tab
2. Select the **CDK Destroy** workflow
3. Click **Run workflow**
4. Enter the branch or tag to use (defaults to `main`)
5. Enter the deployment environment name (defaults to `dev`)
6. Click **Run workflow**

The workflow will:
- Check out your specified branch/tag
- Install all dependencies (Python via uv, Node.js)
- Configure AWS credentials via OIDC
- Destroy all CDK stack resources from AWS

**Warning:** This action is irreversible and will delete all deployed resources including the database and its data. Make sure you have backups if needed before destroying the stack.

## Local Deployment

For local development and testing, you can deploy directly from your machine.

### Requirements

- [uv](https://docs.astral.sh/uv/)
- [docker](https://docs.docker.com/get-started/get-docker/)
- [nvm](https://github.com/nvm-sh/nvm?tab=readme-ov-file#installing-and-updating)
- AWS credentials environment variables configured to point to an account
- **Optional** a `config.yaml` file to override the default deployment settings defined in `config.py`

### Installation

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

### Deploy

First, synthesize the app

```bash
uv run npx cdk synth --all
```

Then, deploy

```bash
uv run npx cdk deploy --all --require-approval never
```

## Set up for workshop

After deployment completes, share the following information with workshop participants.

### Custom Domains

All services are accessible via custom domains following the pattern `{service}.{PROJECT_ID}.eoapi.dev`:

- **Config Lambda**: `https://config.{PROJECT_ID}.eoapi.dev`
- **STAC API**: `https://stac.{PROJECT_ID}.eoapi.dev`
- **Raster API**: `https://raster.{PROJECT_ID}.eoapi.dev`
- **Vector API**: `https://vector.{PROJECT_ID}.eoapi.dev`

For example, with `PROJECT_ID=eoapi-workshop-dev`:
- Config: `https://config.eoapi-workshop-dev.eoapi.dev`
- STAC: `https://stac.eoapi-workshop-dev.eoapi.dev`

### For Organizers

After deployment, retrieve the workshop token from CloudFormation outputs:

```bash
STACK_NAME=your-project-id  # Replace with your PROJECT_ID

# Get the workshop token
WORKSHOP_TOKEN=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='WorkshopToken'].OutputValue" \
  --output text)

echo "Workshop Token: $WORKSHOP_TOKEN"
```

Share this information with participants:

1. **Project ID**: Your `PROJECT_ID` (e.g., `eoapi-workshop-mngislis2025`)
2. **Workshop Token**: The token retrieved above

You can share via:
- Workshop Slack channel
- Email
- Presentation slides
- Printed handouts

**Security note:** The workshop token provides access to database credentials and API endpoints. After the workshop:
- Rotate the token by updating `workshop_token` in your config and redeploying
- Or revoke access by deleting the workshop config Lambda function

### For Participants

When you open a notebook in the workshop environment, you'll be prompted to enter the workshop token. The `workshop_setup.setup()` function will:

1. Read the `PROJECT_ID` from your environment (set by the `start` script)
2. Construct the config Lambda URL: `https://config.{PROJECT_ID}.eoapi.dev`
3. Prompt you for the workshop token
4. Fetch and configure all necessary credentials and API endpoints

All configuration happens automatically - no manual setup required!

### Test the Configuration Endpoint

You can verify that the endpoint works correctly:

```bash
PROJECT_ID=your-project-id  # Replace with your PROJECT_ID
CONFIG_URL="https://config.${PROJECT_ID}.eoapi.dev"

curl -H "Authorization: Bearer $WORKSHOP_TOKEN" $CONFIG_URL | jq .
```

This should return JSON with all configuration values:

```json
{
  "pghost": "...",
  "pgport": "5432",
  "pgdatabase": "postgis",
  "pguser": "...",
  "pgpassword": "...",
  "stac_api_endpoint": "https://stac.your-project-id.eoapi.dev",
  "titiler_pgstac_api_endpoint": "https://raster.your-project-id.eoapi.dev",
  "tipg_api_endpoint": "https://vector.your-project-id.eoapi.dev"
}
```

## Loading Workshop Data

**IMPORTANT**: This step is required for workshop participants to complete the vector notebook (`05-tipg.ipynb`). Load this data once after initial deployment - you do NOT need to reload it when updating workshop content or rotating tokens.

### Load the Level III Ecoregions of North America

This loads the ecoregions dataset used in the vector API workshop notebook.

1. **Get database credentials from CloudFormation**:

```bash
STACK_NAME=your-project-id  # Replace with your PROJECT_ID

PGSTAC_SECRET_ARN=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='PgstacSecret'].OutputValue" \
  --output text)

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

2. **Create schema and prepare for data**:

```bash
psql -c "CREATE SCHEMA IF NOT EXISTS features;"
psql -c "DROP TABLE IF EXISTS features.ecoregions;"
```

3. **Load data using GDAL**:

```bash
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

Once loaded, this data persists in the database and is available for all workshop variants.
