# Registration API Gateway - Client

The `reg-api-client` is a client implementation aimed to support the Data Provider in interfacing with the Registration API, with an S3 staging area backend for assets.

# Execution

There are three ways you can run install this client:

1. locally, via python, installing s5cmd and curl dependencies
2. as a Docker container, available at 
3. as a [CWL](https://www.commonwl.org/)/[OGC Application Package](https://docs.ogc.org/bp/20-089r1.html), into a supported platform

## Local

Ensure you have installed [s5cmd](https://github.com/peak/s5cmd?tab=readme-ov-file#installation), `curl` and `python3` (version 3.9 or grether)

Download the script from this repository and make it executable

```bash
curl -L -o reg-api-client https://github.com/EOEPCA/reg-api/raw/refs/heads/main/client/reg-api-client
chmod +x reg-api-client
```

You can now execute the software locally via

```bash
./reg-api-client --help
```

## Docker

Ensure you have [docker](https://docs.docker.com/engine/install/) installed.

Run the software via

```bash
docker run eoepca/reg-api-client:latest --help
```

## OGC Application Package

The [OGC Application Package](https://docs.ogc.org/bp/20-089r1.html) is a fully fledged [CWL](https://www.commonwl.org/) you can use to deploy and run your application into different platforms and infrastructure. Most notably, you can use:
 - [CWLTool](https://github.com/common-workflow-language/cwltool) to run CWL locally
 - [Toil](https://toil.readthedocs.io/en/latest/) to run CWL on an HPC cluster
 - [OGC API Process Part 2](https://docs.ogc.org/DRAFTS/20-044.html) or the [OpenEO Community Standard UDF](https://open-eo.github.io/openeo-udf/) APIs to deploy and run on an Exploitation Platform

### CWLTool

Locally, after installing [CWLTool](https://github.com/common-workflow-language/cwltool?tab=readme-ov-file#install), you can run the [CWL file](./reg-api-client.cwl) provided in this repository via the following command

```bash
cwltool reg-api-client.cwl --collection PRR_TEST --password test --username test --product http://path/to/stac/to/ingest
```

### Toil

You can install Toil and run the [CWL file](./reg-api-client.cwl) provided in this repository as any other CWL file. NOTE: Ensure you have docker available in your processing cluster.

### Exploitation Platforms

If the `reg-api-client` service is not already installed in your platform, deploy the OGC application package [CWL file](./reg-api-client.cwl) contained in this repository into a supported platform via [OGC API Process Part 2](https://docs.ogc.org/DRAFTS/20-044.html) or the [OpenEO Community Standard UDF](https://open-eo.github.io/openeo-udf/)

Please follow your platform instructions to understand how to perform the deployment, if required, and later run the process using the platform UI or API ([OGC API Process Part 1](https://docs.ogc.org/is/18-062r2/18-062r2.html) or [OpenEO](https://api.openeo.org/))

Note that your platform UI and API will you only allow you to set the main execution parameters.  You can configure all the other parameters, like for example specifying the endpoints of the Registration API Gateway, directly in the [CWL file](./reg-api-client.cwl) before deployment.

# Usage

In general, the tool takes as input the following main parameters,
 - One or more product in the form of STAC Items, STAC Catalogues, STAC Collections or STAC Assets to be ingested via the Registration API Gateway
 - A collection ID, where the product is going to be ingested
 - Credentials for the Registration API gateway

In case a STAC Item is provided in input, its assets will be downloaded and uploaded in the Registration API stagein bucket, then the STAC Item will be posted to the Registration API. If a STAC Catalogue or STAC Collection is provided, it is navigated recursively looking for STAC Items, all the STAC Items found will be ingested in the same Collection ID at the same level. If a STAC Asset is provided, a STAC Item is created with basic metadata and registered.

The input product, whatever STAC Items, STAC Catalogues, STAC Collections or STAC Assets can be provided with a local link, HTTP(s) or S3. 

More details about the tool usage is provided in the help, available via the --help switch.

For installation instructions, examples, dry-run checks, and troubleshooting, see the [Registration API Client User Guide](https://eoresults.esa.int/reg_api_client_user_guide.html).
