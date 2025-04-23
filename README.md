# eoAPI FedGeoDay25 workshop

[![Binder](https://binder.opensci.2i2c.cloud/badge_logo.svg)](https://binder.opensci.2i2c.cloud/v2/gh/developmentseed/eoapi-fedgeoday25-workshop/v0.1?urlpath=%2Fdoc%2Ftree%2Fdocs%2F00-introduction.ipynb)

This repository contains the materials for the eoAPI workshop at FedGeoDay25 in Washington D.C. on April 23, 2025.
The materials will all be contained in Jupyter notebooks that participants can interact with in their web browser via a 2i2c Jupyter Hub provisioned by NASA.

For the in-person workshop we have deployed eoAPI using [eoapi-cdk]() constructs in AWS us-west-2. The urls for the eoAPI APIs are listed below:

- titiler-pgstac: <https://helfmwseh8.execute-api.us-west-2.amazonaws.com/>
- stac-fastapi-pgstac: <https://pj44p72a3g.execute-api.us-west-2.amazonaws.com/>
- tipg: <https://ea1xibo0hd.execute-api.us-west-2.amazonaws.com/>

Participants in the in-person workshop will be provided with credentials for the `pgstac` database so they can interact with it during the tutorials.

After the event we will update the materials so anyone can run the tutorial notebooks on their own computer using a docker network with all of the eoAPI services.

## Local development

This project uses a conda environment file to manage system and Python dependencies.

Create the conda environment:

```bash
conda env create -f environment.yml
```

Activate the conda environment:

```bash
conda activate eoapi-workshop 
```

Start the `jupyter lab` server:

```bash
jupyter lab
```

Then you can browse and interact with the notebooks in the `/docs` folder!
