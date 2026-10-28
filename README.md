# AWS Cost & Infrastructure Optimizer

A Python application that analyzes AWS EC2 infrastructure, collects CloudWatch metrics, maintains historical configuration and metric data in MySQL, evaluates optimization opportunities, estimates potential cost savings, and generates structured JSON reports.

The project also includes a MySQL and OpenSearch data-fetching workflow for retrieving tenant, ingestion-audit, and OpenSearch job information.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [How the Application Works](#2-how-the-application-works)
3. [Technologies Used](#3-technologies-used)
4. [Prerequisites](#4-prerequisites)
5. [Understanding the Project Directory](#5-understanding-the-project-directory)
6. [Python Virtual Environment](#6-python-virtual-environment)
7. [Install Project Dependencies](#7-install-project-dependencies)
8. [Configure Environment Variables](#8-configure-environment-variables)
9. [Start MySQL with Docker](#9-start-mysql-with-docker)
10. [Initialize the Database](#10-initialize-the-database)
11. [Configure AWS Access](#11-configure-aws-access)
12. [Run the Complete Application](#12-run-the-complete-application)
13. [Analyze a Single EC2 Instance](#13-analyze-a-single-ec2-instance)
14. [Understanding the Analysis Results](#14-understanding-the-analysis-results)
15. [CloudWatch Metrics and Evidence Requirements](#15-cloudwatch-metrics-and-evidence-requirements)
16. [Database Structure and Useful Queries](#16-database-structure-and-useful-queries)
17. [MySQL and OpenSearch Data Fetching](#17-mysql-and-opensearch-data-fetching)
18. [Check Metric Data Availability](#18-check-metric-data-availability)
19. [Audit the Database](#19-audit-the-database)
20. [Run Tests](#20-run-tests)
21. [Explanation of the Main Project Files](#21-explanation-of-the-main-project-files)
22. [Common Problems and Solutions](#22-common-problems-and-solutions)
23. [Security and Development Guidelines](#23-security-and-development-guidelines)
24. [Useful Commands Reference](#24-useful-commands-reference)

---

## 1. Project Overview

The AWS Cost & Infrastructure Optimizer helps determine whether an EC2 instance may be oversized, undersized, appropriately sized, or lacking sufficient evidence for a reliable recommendation.

It uses real AWS infrastructure information, actual CloudWatch metrics, historical data stored in MySQL, candidate-instance validation, and AWS pricing information.

### Main capabilities

- Discover AWS identity, regions, and EC2 instances.
- Retrieve EC2 instance configuration and specifications.
- Collect CPU utilization and available memory metrics.
- Record instance configuration snapshots.
- Detect configuration changes over time.
- Store metric observations and datapoints in MySQL.
- Evaluate whether sufficient historical evidence exists.
- Perform deterministic workload and capacity analysis.
- Identify and validate alternative EC2 instance types.
- Retrieve AWS pricing information for cost comparisons.
- Generate optimization recommendations and JSON reports.
- Use AI-assisted reasoning to explain validated results when configured.
- Fetch tenant, ingestion-audit, and OpenSearch information through the ingestion workflow.
- Audit database contents and investigate missing metric data.

### Important safety rule

**The EC2 optimization workflow is read-only against AWS infrastructure.**

It does not stop, start, reboot, terminate, resize, or modify EC2 instances. Its purpose is to analyze resources and produce recommendations, not to apply them automatically.

---

## 2. How the Application Works

The complete workflow can be understood as two connected parts.

### Part A: EC2 optimization

```text
Start application
       |
       v
Load configuration from environment
       |
       v
Connect to MySQL
       |
       v
Identify AWS account and regions
       |
       v
Discover EC2 instances
       |
       v
Collect current instance configuration
       |
       v
Compare with historical configuration
       |
       +---- Configuration changed
       |          |
       |          v
       |    Record configuration change
       |    Start a new evidence period
       |
       v
Collect CloudWatch metrics
       |
       v
Store metric history in MySQL
       |
       v
Validate metric and configuration evidence
       |
       +---- Evidence insufficient
       |          |
       |          v
       |    Report INSUFFICIENT_DATA
       |
       v
Analyze workload and capacity
       |
       v
Find and validate EC2 candidates
       |
       v
Retrieve AWS pricing
       |
       v
Generate recommendation
       |
       v
Apply optional AI-assisted explanation
       |
       v
Write JSON analysis report
```

### Part B: MySQL and OpenSearch integration

When the complete entry-point workflow enables ingestion processing, it also runs the integration that retrieves relevant MySQL and OpenSearch data.

```text
EC2 analysis report
       |
       v
Read active tenant information
       |
       v
Retrieve Super Index module information
       |
       v
Retrieve completed ingestion audits
       |
       v
Find matching OpenSearch job records
       |
       v
Write structured JSON output
```

The EC2 analysis report and the ingestion/OpenSearch outputs are separate results. An ingestion failure does not necessarily mean that EC2 analysis itself failed; check the console output and the report files.

---

## 3. Technologies Used

| Technology           | Purpose                                 |
| -------------------- | --------------------------------------- |
| Python 3.12 or newer | Application programming language        |
| `boto3`              | Communication with AWS services         |
| Amazon CloudWatch    | EC2 CPU and available memory metrics    |
| MySQL 8.4            | Persistent historical records           |
| Docker Compose       | Runs the local MySQL service            |
| PyMySQL              | Connects Python scripts to MySQL        |
| OpenSearch           | Stores and serves indexed job records   |
| `opensearch-py`      | Python client for OpenSearch            |
| `python-dotenv`      | Loads environment variables from `.env` |
| OpenAI API           | Optional AI-assisted explanations       |
| `pytest`             | Runs automated tests                    |
| `rich`               | Formats terminal output                 |

The dependency versions are defined in `pyproject.toml`.

---

## 4. Prerequisites

Before running the application, install or configure the following:

1. Python 3.12 or newer.
2. `pip`, the Python package installer.
3. Docker Engine or Docker Desktop.
4. Docker Compose.
5. AWS credentials with the required read-only permissions.
6. MySQL configuration.
7. OpenSearch credentials if you intend to run the ingestion/OpenSearch workflow.
8. An OpenAI API key if AI-assisted reasoning is required.

Verify the installed tools:

```bash
python3 --version
python3 -m pip --version
docker --version
docker compose version
git --version
```

You do not need Docker to access AWS. Docker is used here to run the local MySQL database.

### Open the project directory

Navigate to the directory containing `pyproject.toml` and `docker-compose.yml`.

For example:

```bash
cd ~/Documents/Cost-Optimizer
```

The directory shown above is only an example. Use the actual location of your project.

**Run the commands in this README from the project root unless stated otherwise.**

---

## 5. Understanding the Project Directory

The project is organized into modules so that AWS communication, database operations, analysis, tracking, and reporting remain separate.

```text
Cost-Optimizer/
├── app/
│   ├── analysis/
│   ├── auth/
│   ├── aws/
│   ├── database/
│   ├── ec2/
│   ├── pricing/
│   ├── reporting/
│   ├── server/
│   ├── tracking/
│   ├── config.py
│   └── main.py
├── reporting/
├── scripts/
│   └── audit_database.py
├── tests/
│   ├── unit/
│   ├── test_recommendation_policy.py
│   └── test_schema_validator.py
├── analyze_instance.py
├── check_metric_data_availability.py
├── fetch_opensearch_mysql.py
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

Other files may exist depending on the version of the project.

### What are the important root files?

- `README.md`: Main documentation for the project.
- `pyproject.toml`: Declares the Python project, dependencies, and test configuration.
- `.env.example`: Template showing environment variables used for local configuration.
- `.env`: Your local configuration and secrets; do not commit this file.
- `.gitignore`: Tells Git which files and directories should not be tracked.
- `docker-compose.yml`: Defines the local MySQL service and persistent volume.
- `analyze_instance.py`: Runs an analysis for one selected EC2 instance.
- `fetch_opensearch_mysql.py`: Fetches selected MySQL and OpenSearch datasets.
- `check_metric_data_availability.py`: Inspects stored CloudWatch metric availability.
- `scripts/audit_database.py`: Audits the database and generates a diagnostic report.
- `app/main.py`: Main application entry point.

---

## 6. Python Virtual Environment

### 6.1 What is a virtual environment?

A Python virtual environment is an isolated Python environment for a specific project.

A Python application often needs external libraries such as `boto3`, `PyMySQL`, `openai`, and `pytest`.

Installing every package globally can cause conflicts between projects. For example, one project might require a different version of a library than another project.

A virtual environment keeps the project's Python packages separate from the system Python installation and other projects.

### 6.2 Why do we use it?

A virtual environment helps you:

- Keep project dependencies isolated.
- Avoid changing system-wide Python packages.
- Reduce dependency conflicts between projects.
- Reproduce the development environment.
- Install and test project dependencies safely.

The environment is normally stored in a directory named `.venv`.

It does not contain your application's source code. It contains the Python environment and installed packages used to run the code.

### 6.3 Create a virtual environment

From the project root, run:

```bash
python3 -m venv .venv
```

This creates a `.venv` directory.

If Python's virtual environment support is missing on Ubuntu or Debian, install the appropriate system package first:

```bash
sudo apt update
sudo apt install python3-venv
```

Then create the environment again.

### 6.4 Activate the virtual environment

On Linux or macOS:

```bash
source .venv/bin/activate
```

After activation, the terminal prompt usually shows:

```text
(.venv)
```

This indicates that the environment is active.

Verify the Python executable:

```bash
which python
python --version
```

The executable path should point inside the project's `.venv` directory.

### 6.5 Install dependencies inside the environment

With `.venv` active, run:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `-e` option installs the project in editable mode. Changes to the project's Python source files can be used without reinstalling the project after every edit.

The `[dev]` part also installs the optional development dependencies, including `pytest`.

### 6.6 Activate it next time

A virtual environment does not automatically activate whenever you open a terminal.

Each new terminal session should start with:

```bash
cd ~/Documents/Cost-Optimizer
source .venv/bin/activate
```

Replace the example path with your actual project directory.

### 6.7 Deactivate it

When you want to leave the environment:

```bash
deactivate
```

Deactivating the environment does not delete it or remove the packages installed in it.

### 6.8 Should `.venv` be committed to Git?

No. The virtual environment is machine-specific and can be recreated using `pyproject.toml`.

Keep `.venv/` in `.gitignore`.

---

## 7. Install Project Dependencies

The project's Python dependencies are defined in `pyproject.toml`.

Install the application and its development dependencies:

```bash
python -m pip install -e ".[dev]"
```

To install only the project and its main dependencies:

```bash
python -m pip install -e .
```

### What does `pyproject.toml` do?

It defines:

- Project name and version.
- Minimum supported Python version.
- Required Python packages.
- Optional development dependencies.
- Package discovery settings.
- Pytest configuration.

Using a dependency file is better than manually installing packages one by one because the environment can be recreated consistently.

### Verify important dependencies

```bash
python -c "import boto3, openai, pymysql, dotenv, opensearchpy, rich; print('Dependencies OK')"
```

If you receive an import error, confirm that the virtual environment is active and reinstall the dependencies.

---

## 8. Configure Environment Variables

The application reads configuration from environment variables. It uses `python-dotenv` to load values from a `.env` file.

### 8.1 Create `.env`

From the project root:

```bash
cp .env.example .env
```

Open the new file in your editor:

```bash
nano .env
```

Update the values to match your environment.

### 8.2 Example configuration

```dotenv
# AWS
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=
AWS_DEFAULT_REGION=us-east-1

# Optional AI reasoning
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-luna

# Analysis configuration
ANALYSIS_HOURS=1
REQUIRED_EVIDENCE=1h
RECOMMENDATION_COOLDOWN_DAYS=30
ANALYSIS_COOLDOWN_DAYS=30

# Logging
LOG_LEVEL=INFO

# Local MySQL
DATABASE_URL=mysql+pymysql://optimizer:optimizer_dev_password@127.0.0.1:3307/cost_optimizer
```

These are example development settings. Use the actual credentials and settings required by your environment.

**Important:** The application's configuration loader reads `ANALYSIS_HOURS` for the analysis window. Do not assume that setting `ANALYSIS_DAYS` changes the main application's analysis window.

### 8.3 What do these variables mean?

| Variable                       | Purpose                                                   |
| ------------------------------ | --------------------------------------------------------- |
| `AWS_ACCESS_KEY_ID`            | Optional AWS access key                                   |
| `AWS_SECRET_ACCESS_KEY`        | Optional AWS secret key                                   |
| `AWS_SESSION_TOKEN`            | Optional temporary-session token                          |
| `AWS_DEFAULT_REGION`           | Default AWS region                                        |
| `OPENAI_API_KEY`               | API key for AI-assisted reasoning                         |
| `OPENAI_MODEL`                 | Model name used by the reasoning component                |
| `ANALYSIS_HOURS`               | Analysis window in hours                                  |
| `REQUIRED_EVIDENCE`            | Required evidence duration, such as `1h`, `24h`, or `30d` |
| `RECOMMENDATION_COOLDOWN_DAYS` | Recommendation lifecycle cooldown                         |
| `ANALYSIS_COOLDOWN_DAYS`       | Analysis lifecycle cooldown                               |
| `LOG_LEVEL`                    | Logging verbosity                                         |
| `DATABASE_URL`                 | MySQL connection URL                                      |

The configuration loader validates important settings such as analysis duration, evidence duration, cooldown values, and database URL format.

### 8.4 Why is the database port `3307`?

The project's Docker Compose configuration maps:

```yaml
ports:
  - "3307:3306"
```

The first port is the port on your computer. The second port is the port inside the MySQL container.

Therefore:

- Python running on your computer connects to `127.0.0.1:3307`.
- Another container on the same Compose network can normally connect to the MySQL service using `mysql:3306`.

Use the host port in your local `.env` file.

### 8.5 Protect your secrets

Never commit `.env`, AWS credentials, OpenAI keys, or production database passwords to Git.

The `.env.example` file should contain variable names and safe examples, not real secrets.

---

## 9. Start MySQL with Docker

The project uses MySQL 8.4 for persistent application data.

Docker Compose starts MySQL without requiring you to install the database server directly on your computer.

### 9.1 Check Docker

```bash
docker --version
docker compose version
```

Make sure Docker is running before continuing.

### 9.2 Start MySQL

From the project root:

```bash
docker compose up -d
```

The `-d` option runs the container in the background.

### 9.3 Check container status

```bash
docker compose ps
```

The configured container name is:

```text
cost-optimizer-mysql
```

Wait until the MySQL health check reports that the service is healthy.

### 9.4 View MySQL logs

```bash
docker compose logs -f mysql
```

Press `Ctrl+C` to stop following the logs. This does not stop the container.

### 9.5 Database configuration

The current local Compose configuration uses:

| Setting           | Value                       |
| ----------------- | --------------------------- |
| MySQL image       | `mysql:8.4`                 |
| Container name    | `cost-optimizer-mysql`      |
| Database          | `cost_optimizer`            |
| Application user  | `optimizer`                 |
| Host port         | `3307`                      |
| Container port    | `3306`                      |
| Persistent volume | `cost_optimizer_mysql_data` |

The Compose file currently contains development credentials. Change them before using this setup in a shared or production environment, and make sure your `.env` connection URL matches.

### 9.6 Connect to MySQL

Run:

```bash
docker exec -it cost-optimizer-mysql mysql -u optimizer -p cost_optimizer
```

Enter the configured application user's password when prompted.

Useful commands inside the MySQL shell:

```sql
SHOW TABLES;
SELECT DATABASE();
```

Exit the shell:

```sql
EXIT;
```

### 9.7 Stop MySQL

```bash
docker compose stop
```

This stops the running service but preserves the database volume.

To start it again:

```bash
docker compose start
```

**Warning:** Removing a persistent Docker volume can delete database data. Do not use volume-removal commands unless you intentionally want to discard the database.

---

## 10. Initialize the Database

Once MySQL is running and `DATABASE_URL` is correct, initialize the application tables.

From the project root, with `.venv` active:

```bash
python -c "from app.database.init import initialize_database; initialize_database(); print('Database initialization completed')"
```

The initialization code is responsible for preparing the database structures used by the application.

### What does database initialization do?

The application needs tables for historical records such as:

- EC2 configuration snapshots.
- Configuration changes.
- Metric observations.
- Metric datapoints.
- Tracking and analysis records.
- Recommendation lifecycle information.
- Cumulative metric records and checkpoints.

The exact schema is defined by the database models and initialization code.

### Verify the tables

Open the MySQL shell:

```bash
docker exec -it cost-optimizer-mysql mysql -u optimizer -p cost_optimizer
```

Then run:

```sql
SHOW TABLES;
```

Inspect a table:

```sql
DESCRIBE metric_datapoints;
```

Exit:

```sql
EXIT;
```

If initialization fails, first check the database container, credentials, port, and database URL.

---

## 11. Configure AWS Access

The application uses `boto3` to access AWS.

It relies on the standard AWS credential resolution process, which can use environment variables, AWS profiles, temporary credentials, or other supported credential providers.

### 11.1 Recommended approach

For local development, use an appropriately restricted AWS profile or another supported credential provider where possible.

For example, if you have configured an AWS CLI profile:

```bash
aws sts get-caller-identity --profile your-profile
```

Configure the environment or AWS profile so that the application can use the intended credentials.

Do not paste real secret keys into the source code.

### 11.2 Verify AWS identity

The project includes an AWS client helper. You can test it with:

```bash
python -c "from app.aws.client import get_aws_client; print(get_aws_client('us-east-1').identity())"
```

This should return identity information for the configured AWS account.

### 11.3 Required permissions

The IAM identity needs the read permissions required by the features you intend to run. These generally include access to the relevant EC2 discovery and description APIs, CloudWatch metric retrieval, and pricing information.

Use the application's actual AWS API calls to create a least-privilege policy. Do not grant broad administrator permissions merely to make an access error disappear.

For the memory metric, the relevant CloudWatch Agent metric must already be published by the EC2 instance.

---

## 12. Run the Complete Application

Before starting, confirm that:

- The virtual environment is active.
- Dependencies are installed.
- `.env` is configured.
- MySQL is running.
- The database is initialized.
- AWS credentials work.
- OpenSearch settings are available if ingestion processing is required.

Run the main entry point:

```bash
python -m app.main
```

The main workflow performs EC2 analysis and, by default, also attempts the ingestion/OpenSearch integration.

The application reports its progress in the terminal.

### Main processing stages

1. Load configuration.
2. Initialize or verify database structures.
3. Resolve AWS identity and region information.
4. Discover EC2 instances.
5. Collect instance configuration and history.
6. Collect and persist metric data.
7. Evaluate evidence requirements.
8. Analyze workload and capacity.
9. Validate alternative instance candidates.
10. Retrieve pricing information.
11. Persist analysis and recommendation records.
12. Generate a JSON report.
13. Run ingestion/OpenSearch processing when enabled.

### Output location

The main EC2 report is normally written to:

```text
output/analysis-result.json
```

Ingestion-related JSON outputs are written under:

```text
output/tenants/
```

The exact files depend on the enabled workflow.

The `output/` directory contains generated data. It should not be treated as source code or committed as part of normal development.

---

## 13. Analyze a Single EC2 Instance

The project provides `analyze_instance.py` to run an analysis for one EC2 instance over a caller-selected time window.

Unlike the complete entry point, this script explicitly runs the EC2 analysis and report-generation path without the ingestion, audit, and OpenSearch integration.

### 13.1 Analyze by days

Example:

```bash
python analyze_instance.py --resource-id i-0123456789abcdef0 --days 1
```

Replace the example instance ID with a real EC2 instance ID accessible to your AWS credentials.

### 13.2 Analyze by hours

```bash
python analyze_instance.py --resource-id i-0123456789abcdef0 --hours 24
```

You must specify either `--days` or `--hours`, not both.

The supported analysis window is between one hour and 90 days.

### 13.3 Specify a region

```bash
python analyze_instance.py --resource-id i-0123456789abcdef0 --days 5 --region us-east-1
```

### 13.4 What does this script do?

- Validates the supplied EC2 instance ID.
- Converts the requested duration into hours.
- Invokes the EC2 analysis workflow for the selected resource.
- Keeps progress output on standard error.
- Prints one JSON result to standard output.
- Avoids running the ingestion/OpenSearch integration.

This makes it useful for scripts and other programs that need to consume the analysis result as JSON.

---

## 14. Understanding the Analysis Results

The optimizer should not recommend a resource change solely because one metric appears low or high.

It evaluates the available evidence, current configuration, workload characteristics, candidate compatibility, capacity requirements, and cost information.

### Common result concepts

| Result               | Meaning                                                    |
| -------------------- | ---------------------------------------------------------- |
| `KEEP_CURRENT`       | Retain the current instance based on the analysis          |
| `DOWNSIZE_CANDIDATE` | A smaller candidate may be suitable, subject to validation |
| `UPSCALE_CANDIDATE`  | A larger candidate may be needed                           |
| `INVESTIGATE`        | More investigation is appropriate before acting            |
| `INSUFFICIENT_DATA`  | Available evidence is not adequate for a reliable decision |

These statuses have different implications. A candidate is not an instruction to change an instance automatically.

### Why can a recommendation be unavailable?

Possible reasons include:

- Missing CPU datapoints.
- Missing memory metrics.
- Incomplete metric coverage.
- Insufficient configuration history.
- A recent configuration change.
- Metrics belonging to a different configuration version.
- Missing pricing or candidate information.
- Incompatible candidate specifications.

When the result is `INSUFFICIENT_DATA`, investigate the evidence and history before treating it as an optimization decision.

---

## 15. CloudWatch Metrics and Evidence Requirements

### 15.1 CPU utilization

The standard EC2 CPU metric is:

```text
Namespace: AWS/EC2
Metric:    CPUUtilization
```

The application collects real CloudWatch observations and stores historical metric data in MySQL.

### 15.2 Memory utilization

The application uses the following memory metric:

```text
Namespace: EC2/Custom
Metric:    mem_used_percent
```

This metric must be published by a correctly configured CloudWatch Agent or an equivalent setup that publishes the expected metric.

AWS does not automatically provide the same guest operating-system memory metric in the same way it provides EC2 CPU utilization.

If the memory metric is absent, the application must not invent a memory value.

### 15.3 Analysis duration versus evidence duration

These are different concepts.

**Analysis duration** is the time window selected for the current analysis.

**Required evidence duration** is how much usable, consistent history must exist before the application can make a reliable decision.

For example, a one-day analysis window does not necessarily mean the instance has one day of valid historical evidence.

The current configuration supports an evidence setting such as:

```dotenv
REQUIRED_EVIDENCE=1h
```

Other examples include:

```dotenv
REQUIRED_EVIDENCE=24h
REQUIRED_EVIDENCE=7d
REQUIRED_EVIDENCE=30d
```

The project configuration validates supported evidence durations, up to 90 days.

The actual evidence policy also depends on the analysis implementation and data quality.

### 15.4 Configuration changes reset the evidence period

The application tracks EC2 configuration snapshots over time.

When a relevant configuration change is detected, the new configuration must establish its own evidence history. Metrics from a previous configuration must not automatically be treated as evidence for the new one.

This prevents a recommendation from relying on a workload history that no longer represents the current instance configuration.

### 15.5 Insufficient data after starting the application

Running the application does not guarantee an immediate recommendation.

The optimizer needs actual metrics and enough valid history for its evidence rules.

If the output is `INSUFFICIENT_DATA`:

1. Check whether CloudWatch metrics exist.
2. Check whether the metrics have been stored in MySQL.
3. Inspect the first and latest datapoint timestamps.
4. Verify the current configuration history.
5. Check for missing metric intervals.
6. Verify that the evidence belongs to the current configuration.
7. Review the report's explanation before changing settings.

Wait for new metric data to accumulate when necessary. One hour of elapsed time does not guarantee one hour of complete, usable evidence.

---

## 16. Database Structure and Useful Queries

MySQL stores the historical information used by the optimizer.

AWS remains the source of truth for the current infrastructure state. MySQL provides the historical context needed to evaluate configuration stability and metric evidence.

### 16.1 Connect to the database

```bash
docker exec -it cost-optimizer-mysql mysql -u optimizer -p cost_optimizer
```

### 16.2 List tables

```sql
SHOW TABLES;
```

### 16.3 Inspect table columns

```sql
DESCRIBE instance_snapshots;
DESCRIBE configuration_changes;
DESCRIBE metric_observations;
DESCRIBE metric_datapoints;
```

If a table name differs in your database, use the names returned by `SHOW TABLES`.

### 16.4 Inspect recent snapshots

```sql
SELECT
    instance_id,
    region,
    instance_type,
    state,
    observed_at
FROM instance_snapshots
ORDER BY observed_at DESC
LIMIT 20;
```

Snapshots help establish which EC2 configuration was observed and when.

### 16.5 Inspect configuration changes

```sql
SELECT
    instance_id,
    region,
    previous_instance_type,
    current_instance_type,
    detected_at
FROM configuration_changes
ORDER BY detected_at DESC
LIMIT 20;
```

Configuration-change records help explain why a previous evidence period may no longer be applicable.

### 16.6 Inspect metric history

```sql
SELECT
    instance_id,
    metric_name,
    COUNT(*) AS datapoints,
    MIN(timestamp) AS first_datapoint,
    MAX(timestamp) AS latest_datapoint
FROM metric_datapoints
GROUP BY instance_id, metric_name
ORDER BY instance_id, metric_name;
```

This query shows the number of stored datapoints and the range of timestamps for each instance and metric.

### 16.7 Inspect recent datapoints

```sql
SELECT
    instance_id,
    namespace,
    metric_name,
    timestamp,
    average,
    minimum,
    maximum
FROM metric_datapoints
ORDER BY timestamp DESC
LIMIT 20;
```

### 16.8 Exit MySQL

```sql
EXIT;
```

**Important:** Table columns and schemas can change as the application evolves. Inspect the live schema before using a query against a database created by a different project version.

---

## 17. MySQL and OpenSearch Data Fetching

The project includes a separate workflow for fetching MySQL ingestion information and OpenSearch documents.

The command-line entry point is:

```text
fetch_opensearch_mysql.py
```

This workflow is separate from the EC2 metric analysis.

### 17.1 Fetch active tenants

```bash
python fetch_opensearch_mysql.py --active-tenants
```

This retrieves active tenant information.

### 17.2 Fetch Super Index module information

```bash
python fetch_opensearch_mysql.py --superindex-module-id
```

This retrieves information about the `super_index` module and its identifier.

### 17.3 Fetch completed ingestion audits

```bash
python fetch_opensearch_mysql.py --data-ingestion-audit
```

This retrieves completed ingestion audit information.

### 17.4 Fetch OpenSearch documents

```bash
python fetch_opensearch_mysql.py --opensearch
```

This retrieves OpenSearch documents for active tenants, subject to the configured connection and index availability.

### 17.5 Required configuration

The workflow needs valid connection settings for the external MySQL source and OpenSearch.

Configure the expected environment variables in `.env` according to the connection helpers in:

```text
app/auth/remote_db_connection.py
app/auth/opensearch_connection.py
```

Do not put production credentials directly into Python source files or commit them to Git.

### 17.6 Generated data

The integration can generate JSON files under:

```text
output/tenants/
```

These files are generated data, not source files.

The complete application also has an integration step that combines relevant ingestion/OpenSearch information with the wider workflow. If this stage fails, check its connection configuration and error output separately from the EC2 analysis report.

---

## 18. Check Metric Data Availability

The script:

```text
check_metric_data_availability.py
```

inspects CloudWatch metric records already stored in MySQL.

It is intended for diagnostics. It does not collect new CloudWatch metrics or modify the database.

### 18.1 Basic check

```bash
python check_metric_data_availability.py
```

### 18.2 Filter by EC2 instance

```bash
python check_metric_data_availability.py --instance-id i-0123456789abcdef0
```

### 18.3 Filter by region

```bash
python check_metric_data_availability.py --region us-east-1
```

### 18.4 Filter by metric

```bash
python check_metric_data_availability.py --metric CPUUtilization
```

### 18.5 Filter by namespace

```bash
python check_metric_data_availability.py --namespace AWS/EC2
```

### 18.6 Show missing calendar dates

```bash
python check_metric_data_availability.py --show-missing-days
```

### 18.7 Show aggregate totals only

```bash
python check_metric_data_availability.py --summary-only
```

The script reports information such as the earliest and latest stored datapoints, the dates containing data, missing dates inside the available range, and recorded observation coverage.

A missing database datapoint does not by itself prove that CloudWatch never published the datapoint. This script audits the records already stored in MySQL.

---

## 19. Audit the Database

The project includes a read-only database audit utility:

```text
scripts/audit_database.py
```

It checks database structures and historical data that may affect analysis reliability.

### 19.1 Run the default audit

```bash
python scripts/audit_database.py
```

The default JSON report is:

```text
output/database-audit-report.json
```

### 19.2 Audit a time window

For example, audit the last 72 hours:

```bash
python scripts/audit_database.py --hours 72
```

### 19.3 Audit a specific EC2 instance

```bash
python scripts/audit_database.py --instance-id i-0123456789abcdef0
```

Combine the instance filter with a time window:

```bash
python scripts/audit_database.py --instance-id i-0123456789abcdef0 --hours 72
```

### 19.4 Audit a particular date

```bash
python scripts/audit_database.py --date 2026-10-27
```

### 19.5 Audit all available history

```bash
python scripts/audit_database.py --all-history
```

### 19.6 Specify a report path

```bash
python scripts/audit_database.py --report output/my-database-audit.json
```

The audit utility checks the actual supported arguments in its command-line parser. Use the following command to see the available options for your installed version:

```bash
python scripts/audit_database.py --help
```

### What does the audit check?

Depending on the selected scope, it can examine:

- Required database tables and columns.
- Stored CPU and memory datapoints.
- Missing or incomplete metric intervals.
- Metric checkpoint consistency.
- Cumulative metric summaries.
- Observation windows.
- Analysis runs and recommendation records.
- Snapshot and configuration-history information.
- Missing or unexpected database values.

The audit is intended to identify issues and suggest diagnostic steps. It does not automatically repair database records or modify AWS resources.

---

## 20. Run Tests

Automated tests help verify configuration parsing, recommendation policies, schema validation, eligibility rules, recommendation lifecycle behavior, and configuration-evidence handling.

Ensure that the virtual environment is active and development dependencies are installed.

### 20.1 Run the complete test suite

```bash
python -m pytest
```

### 20.2 Run unit tests

```bash
python -m pytest tests/unit/
```

### 20.3 Run a specific test file

For example:

```bash
python -m pytest tests/unit/test_config.py
```

Or:

```bash
python -m pytest tests/test_schema_validator.py
```

### 20.4 Run tests with more detail

```bash
python -m pytest -v
```

### 20.5 Compile-check Python files

For a quick syntax check of the main entry point:

```bash
python -m py_compile app/main.py
```

For the instance-analysis script:

```bash
python -m py_compile analyze_instance.py
```

A passing unit test suite does not prove that external AWS, MySQL, or OpenSearch credentials are valid. Integration behavior also depends on the environment in which the application runs.

---

## 21. Explanation of the Main Project Files

This section explains the purpose of the major modules so a developer can understand where to make changes.

### 21.1 Application configuration

**`app/config.py`**

Loads and validates environment-based application settings, including AWS region, analysis duration, evidence requirements, database configuration, OpenAI configuration, cooldowns, and logging.

**`app/main.py`**

Main application entry point. Coordinates the EC2 optimization workflow and invokes the ingestion/OpenSearch integration when enabled.

### 21.2 AWS integration — `app/aws/`

**`app/aws/client.py`**

Provides the AWS client functionality used by the application, including identity-related operations.

**`app/aws/regions.py`**

Contains region-related functionality used during AWS discovery.

**`app/aws/__init__.py`**

Marks the AWS integration directory as a Python package.

### 21.3 EC2 integration — `app/ec2/`

**`app/ec2/discovery.py`**

Discovers EC2 instances and their current resource information.

**`app/ec2/specs.py`**

Handles EC2 instance specification information used by analysis and candidate validation.

**`app/ec2/metrics.py`**

Collects CloudWatch metrics and calculates metric coverage information used by the evidence workflow.

**`app/ec2/configuration_history.py`**

Supports tracking and evaluating the historical stability of EC2 configuration.

**`app/ec2/__init__.py`**

Marks the EC2 directory as a Python package.

### 21.4 Database — `app/database/`

**`app/database/connection.py`**

Manages database connection functionality.

**`app/database/models.py`**

Defines the main database models and related structures.

**`app/database/cumulative_models.py`**

Defines structures for cumulative metric data.

**`app/database/init.py`**

Initializes the database structures required by the application.

**`app/database/__init__.py`**

Marks the database directory as a Python package.

### 21.5 Analysis — `app/analysis/`

**`app/analysis/eligibility.py`**

Evaluates whether a resource meets the application's eligibility requirements.

**`app/analysis/readiness_report.py`**

Builds readiness information that helps explain whether analysis can proceed.

**`app/analysis/evidence.py`**

Evaluates whether available metric and configuration evidence is sufficient for analysis.

**`app/analysis/metric_statistics.py`**

Calculates statistics from available metrics.

**`app/analysis/workload_analysis.py`**

Analyzes workload utilization.

**`app/analysis/capacity_analysis.py`**

Evaluates capacity requirements and resource headroom.

**`app/analysis/candidate_analysis.py`**

Analyzes alternative EC2 instance candidates.

**`app/analysis/candidate_validation.py`**

Validates candidate compatibility and other candidate requirements.

**`app/analysis/recommendation_policy.py`**

Contains rules used to determine recommendation outcomes.

**`app/analysis/recommendation_lifecycle.py`**

Manages recommendation lifecycle behavior.

**`app/analysis/optimization_impact.py`**

Calculates the expected impact of a potential optimization.

**`app/analysis/ec2_optimizer.py`**

Coordinates core EC2 optimization logic.

**`app/analysis/schema_validator.py`**

Validates analysis output against the expected schema.

**`app/analysis/persistence.py`**

Persists analysis-related results.

**`app/analysis/ai_reasoning.py`**

Provides AI-assisted reasoning and explanations based on available analysis evidence.

AI explanations do not replace deterministic validation or make missing AWS data valid.

### 21.6 Pricing — `app/pricing/`

**`app/pricing/ec2_pricing.py`**

Retrieves EC2 pricing information and supports cost estimation for candidate comparisons.

### 21.7 Tracking — `app/tracking/`

The tracking package stores and manages historical information used across repeated executions.

| File                                    | Purpose                                      |
| --------------------------------------- | -------------------------------------------- |
| `models.py`                             | Tracking-related data models                 |
| `repository.py`                         | Shared tracking repository functionality     |
| `tracker.py`                            | Resource tracking coordination               |
| `snapshot.py`                           | Resource and analysis snapshot functionality |
| `change_detector.py`                    | Detects relevant configuration changes       |
| `change_repository.py`                  | Persists configuration-change records        |
| `execution_context.py`                  | Tracks analysis execution context            |
| `execution_repository.py`               | Persists execution records                   |
| `analysis_repository.py`                | Persists analysis tracking information       |
| `metric_repository.py`                  | Provides metric data access and persistence  |
| `metric_tracker.py`                     | Tracks metric collection                     |
| `datapoint_repository.py`               | Persists metric datapoints                   |
| `metric_checkpoint_repository.py`       | Manages metric collection checkpoints        |
| `cumulative_repository.py`              | Persists cumulative metric records           |
| `cumulative_metrics.py`                 | Processes cumulative metric information      |
| `recommendation_repository.py`          | Persists recommendation records              |
| `recommendation_snapshot_repository.py` | Manages recommendation snapshots             |

The tracking modules help preserve historical evidence across multiple application runs.

### 21.8 Reporting — `app/reporting/` and `reporting/`

**`app/reporting/json_report.py`**

Generates JSON analysis reports.

**`app/reporting/cli.py`**

Provides reporting-related command-line functionality.

**`reporting/cli_report.py`**

Provides a standalone CLI reporting entry point.

### 21.9 External data connections — `app/auth/`

**`app/auth/remote_db_connection.py`**

Provides connection functionality for the external MySQL data source used by the ingestion workflow.

**`app/auth/opensearch_connection.py`**

Provides connection functionality for OpenSearch.

### 21.10 Ingestion and OpenSearch — `app/server/`

**`app/server/active_tenant.py`**

Retrieves active tenant information.

**`app/server/superindex_module_id.py`**

Retrieves Super Index module information.

**`app/server/data_ingestion_audit.py`**

Retrieves ingestion audit information.

**`app/server/opensearch_index.py`**

Fetches OpenSearch index records.

**`app/server/reorder_opensearch_index.py`**

Provides functionality for ordering OpenSearch records.

**`app/server/fetch_ingestion_opensearch.py`**

Coordinates the ingestion and OpenSearch fetching workflow.

### 21.11 Utility scripts

**`analyze_instance.py`**

Runs a single-resource EC2 analysis and emits JSON output.

**`fetch_opensearch_mysql.py`**

Provides command-line options for fetching the supported MySQL and OpenSearch datasets.

**`check_metric_data_availability.py`**

Inspects stored metric coverage and missing dates.

**`scripts/audit_database.py`**

Audits database records and writes a diagnostic JSON report.

### 21.12 Tests

The `tests/` directory contains automated tests for configuration, eligibility, recommendation behavior, schema validation, and configuration-evidence handling.

Tests should be updated whenever the corresponding application behavior changes.

---

## 22. Common Problems and Solutions

### Problem 1: `python` or `pip` is not found

Check the Python installation:

```bash
python3 --version
```

Use the virtual environment's activation command:

```bash
source .venv/bin/activate
```

Use:

```bash
python -m pip install -e ".[dev]"
```

This helps ensure that the correct Python environment receives the packages.

### Problem 2: `ModuleNotFoundError`

Activate the virtual environment and install the project dependencies:

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run project commands from the root directory.

### Problem 3: MySQL connection refused

Check whether the container is running:

```bash
docker compose ps
```

Check the logs:

```bash
docker compose logs mysql
```

Confirm that `DATABASE_URL` uses the host port configured in Docker Compose. In this project, the local host port is `3307`.

### Problem 4: `Access denied for user`

Verify the database username and password in `.env` against the MySQL configuration.

If the database volume was initialized previously, changing environment variables in the Compose file does not necessarily change the credentials already stored in that existing database.

Do not delete the volume simply to resolve a login issue; inspect the existing configuration and data first.

### Problem 5: AWS credentials are unavailable

Verify the identity:

```bash
aws sts get-caller-identity
```

If using a named profile:

```bash
aws sts get-caller-identity --profile your-profile
```

Make sure the application's credential provider is configured for the same identity.

### Problem 6: AWS access denied

The current AWS identity may lack a required permission.

Identify the failed API operation and add only the required read permission to the intended IAM policy. Do not grant unrestricted access as a workaround.

### Problem 7: Memory metrics are missing

Check whether the CloudWatch Agent is configured to publish the expected memory metric:

```text
Namespace: EC2/Custom
Metric:    mem_used_percent
```

Then inspect the stored records:

```bash
python check_metric_data_availability.py --metric mem_used_percent
```

Missing memory data can prevent the application from producing a reliable recommendation.

### Problem 8: Analysis returns `INSUFFICIENT_DATA`

Inspect metric availability:

```bash
python check_metric_data_availability.py
```

Run a database audit:

```bash
python scripts/audit_database.py
```

Review the first and latest datapoint timestamps, missing dates, observation coverage, and configuration history.

Do not reduce evidence requirements solely to force a recommendation. First establish whether the available data is complete and applicable to the current configuration.

### Problem 9: OpenSearch connection fails

Check the environment variables expected by `app/auth/opensearch_connection.py`.

Confirm that:

- The OpenSearch endpoint is correct.
- The credentials are valid.
- The network can reach the endpoint.
- The account has the required read permissions.
- The expected tenant indices exist.

Test the OpenSearch workflow separately from the EC2 analysis to isolate the problem.

### Problem 10: JSON output is missing

Check the terminal output for the actual report path and any reported exceptions.

For the main analysis, inspect:

```text
output/analysis-result.json
```

For database auditing, inspect:

```text
output/database-audit-report.json
```

The output directory may need to be created by the application or the relevant utility. Verify that the process has permission to write to the selected location.

### Problem 11: Tests fail

Run the failing test by itself:

```bash
python -m pytest -v tests/unit/test_config.py
```

Read the traceback and identify whether the failure relates to configuration, database state, external credentials, or application behavior.

Do not assume that all tests require live AWS access. Start with the isolated test and its setup.

---

## 23. Security and Development Guidelines

Follow these principles when developing or deploying the project.

### Credentials

- Never commit `.env`.
- Never hardcode production AWS keys.
- Never hardcode production database passwords.
- Keep OpenAI and OpenSearch credentials outside source code.
- Use restricted credentials and least-privilege permissions.
- Rotate credentials if they are accidentally exposed.

### AWS safety

- Keep the EC2 optimization workflow read-only.
- Do not add automatic resource modification without an explicit, reviewed design change.
- Treat current AWS state as the source of truth.
- Use validated data for recommendations.
- Do not fabricate missing metrics or pricing.

### Evidence quality

- Do not mix metrics from different EC2 configurations.
- Do not treat a checkpoint as proof that valid datapoints exist.
- Check coverage and timestamps before relying on historical summaries.
- Preserve the `INSUFFICIENT_DATA` outcome when evidence is inadequate.

### Git hygiene

Do not commit generated or environment-specific files such as:

```text
.venv/
__pycache__/
.pytest_cache/
output/
.env
```

The `.gitignore` file should exclude local dependencies, secrets, caches, compiled Python files, and generated reports as appropriate.

Do not commit `build/lib/` as a second copy of the source package. Make changes to the actual source under `app/`.

### Database safety

- Review database changes before applying them.
- Avoid deleting historical metric or configuration data without understanding its effect on analysis.
- Be especially careful with Docker volume-removal commands.
- Treat database audit results as diagnostic information, not permission to make automatic repairs.

---

## 24. Useful Commands Reference

### Activate the virtual environment

```bash
source .venv/bin/activate
```

### Install dependencies

```bash
python -m pip install -e ".[dev]"
```

### Start MySQL

```bash
docker compose up -d
```

### Check MySQL

```bash
docker compose ps
```

### View MySQL logs

```bash
docker compose logs -f mysql
```

### Initialize database tables

```bash
python -c "from app.database.init import initialize_database; initialize_database(); print('Database initialized')"
```

### Run the complete application

```bash
python -m app.main
```

### Analyze one EC2 instance

```bash
python analyze_instance.py --resource-id i-0123456789abcdef0 --days 1
```

### Check metric availability

```bash
python check_metric_data_availability.py
```

### Audit the database

```bash
python scripts/audit_database.py
```

### Fetch active tenants

```bash
python fetch_opensearch_mysql.py --active-tenants
```

### Fetch ingestion audits

```bash
python fetch_opensearch_mysql.py --data-ingestion-audit
```

### Fetch OpenSearch records

```bash
python fetch_opensearch_mysql.py --opensearch
```

### Run tests

```bash
python -m pytest
```

### Deactivate the virtual environment

```bash
deactivate
```

---

## Final Architecture Summary

The Cost-Optimizer separates its responsibilities into distinct layers:

- **AWS integration** discovers current resources and retrieves metrics.
- **EC2 modules** handle discovery, specifications, and configuration history.
- **MySQL** stores historical observations, configuration snapshots, metrics, and analysis records.
- **Analysis modules** evaluate evidence, workload, capacity, candidates, and recommendation policies.
- **Pricing modules** support real cost comparisons.
- **AI reasoning** provides explanations based on the validated analysis.
- **Reporting modules** produce structured JSON results.
- **Tracking modules** maintain history between application executions.
- **Ingestion/OpenSearch modules** retrieve tenant, ingestion-audit, and indexed job information.
- **Diagnostic utilities** inspect metric availability and database consistency.
- **Tests** verify important application behavior.

The goal is to produce explainable, evidence-based recommendations without modifying AWS resources automatically.

For normal development, start with this README, keep configuration in `.env`, install dependencies inside `.venv`, use Docker Compose for local MySQL, and run the tests after changing the application.
