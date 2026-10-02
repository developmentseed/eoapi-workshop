# The spike Lab image plus jupyterhub-singleuser, for the z2jh front door.
#   docker build -t eoapi-spike-hub-lab spike/hub   (after spike/lab is built)
FROM eoapi-spike-lab

USER root
# Same version as the hub (z2jh 4.4.2 ships JupyterHub 5.5.2).
RUN /entrypoint.sh pip install --no-cache-dir jupyterhub==5.5.2
USER jovyan

# Replaces the standalone config: login, port and base URL come from the hub.
COPY --chown=jovyan:jovyan jupyter_server_config.py /home/jovyan/.jupyter/jupyter_server_config.py
