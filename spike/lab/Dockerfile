# Build the base first (repo root):
#   docker build -f Dockerfile.local -t eoapi-spike-lab-base .
FROM eoapi-spike-lab-base

USER root
RUN /entrypoint.sh pip install --no-cache-dir jupyter-server-proxy==4.6.0
USER jovyan

COPY --chown=jovyan:jovyan jupyter_server_config.py /home/jovyan/.jupyter/jupyter_server_config.py

EXPOSE 18888
# Port, auth and proxy routes all come from jupyter_server_config.py.
CMD ["jupyter", "lab"]
