# eoAPI FedGeoDay25 workshop

[![Binder](https://binder.opensci.2i2c.cloud/badge_logo.svg)](https://binder.opensci.2i2c.cloud/v2/gh/developmentseed/eoapi-fedgeoday25-workshop/HEAD)

The eoAPI stack is deployed in AWS us-west-2:

- titiler-pgstac: <https://helfmwseh8.execute-api.us-west-2.amazonaws.com/>
- stac-fastapi-pgstac: <https://pj44p72a3g.execute-api.us-west-2.amazonaws.com/>
- tipg: <https://ea1xibo0hd.execute-api.us-west-2.amazonaws.com/>

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
