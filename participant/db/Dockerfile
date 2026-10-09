# pgstac with the workshop data baked in. Every fetch happens at BUILD time;
# the first start (empty data directory) loads the baked SQL from
# /docker-entrypoint-initdb.d with no network access. Replaces compose's
# features-loader (apt-get + S3 at startup) and adds the glad collection.

ARG PGSTAC_TAG=v0.9.11

# --- ecoregions: shapefile -> plain SQL (same ogr2ogr options as compose) ---
FROM ghcr.io/osgeo/gdal:ubuntu-small-latest AS ecoregions
ARG ECOREGIONS_URL=https://dmap-prod-oms-edc.s3.us-east-1.amazonaws.com/ORD/Ecoregions/cec_na/NA_CEC_Eco_Level3.zip
ADD ${ECOREGIONS_URL} /data/NA_CEC_Eco_Level3.zip
RUN ogr2ogr -f PGDump /data/ecoregions.sql \
      /vsizip//data/NA_CEC_Eco_Level3.zip/NA_CEC_Eco_Level3.shp \
      -nln ecoregions -t_srs EPSG:4326 \
      -lco SCHEMA=features -lco CREATE_SCHEMA=ON -lco DROP_TABLE=IF_EXISTS \
      -lco GEOMETRY_NAME=geom -lco FID=id -lco PRECISION=NO \
      -nlt PROMOTE_TO_MULTI \
 && gzip -9 /data/ecoregions.sql

# --- glad: collection + its tiles over North America and Europe (with the UK)
# from the MAAP STAC -> pgstac upserts. BBOXES: w,s,e,n per region (152 tiles).
FROM python:3.12-slim AS glad
ARG STAC_SOURCE=https://stac.maap-project.org
ARG COLLECTION=glad-global-forest-change-1.11
ARG BBOXES="-170,10,-50,75 -25,34,45,72"
COPY glad_to_sql.py /glad_to_sql.py
RUN python /glad_to_sql.py "$STAC_SOURCE" "$COLLECTION" $BBOXES > /glad.sql \
 && gzip -9 /glad.sql

FROM ghcr.io/stac-utils/pgstac:${PGSTAC_TAG}
# zz_ sorts after the image's own 990_pgstac.sh / 999_pgstac.sql in any locale.
COPY initdb/zz_00_tuning.sh /docker-entrypoint-initdb.d/
COPY --from=ecoregions /data/ecoregions.sql.gz /docker-entrypoint-initdb.d/zz_10_ecoregions.sql.gz
COPY --from=glad /glad.sql.gz /docker-entrypoint-initdb.d/zz_20_glad.sql.gz
