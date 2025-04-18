# eoAPI deployment

Template repository to deploy [eoapi](https://eoapi.dev) on AWS using the [eoapi-cdk constructs](https://github.com/developmentseed/eoapi-cdk) or locally with Docker.

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

### Load the Terrestrial Ecoregions of the World features into a postgis table

```bash
PGSTAC_STACK=eoapi-fedgeoday25
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

psql -c "CREATE SCHEMA features;"
psql -c "DROP TABLE features.terrestrial_ecoregions;"
# download from WWF site not working with wget so download from browser...
# wget https://files.worldwildlife.org/wwfcmsprod/files/Publication/file/6kcchn7e3u_official_teow.zip -O /tmp/6kcchn7e3u_official_teow.zip
ogr2ogr -f "PostgreSQL" \
  PG:"postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}" \
  /vsizip//tmp/6kcchn7e3u_official_teow.zip/official/wwf_terr_ecos.shp \
  -nln features.terrestrial_ecoregions \
  -lco GEOMETRY_NAME=geom \
  -lco FID=id \
  -lco PRECISION=NO \
  -nlt PROMOTE_TO_MULTI
```
