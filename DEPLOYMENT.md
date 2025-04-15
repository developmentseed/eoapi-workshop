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
