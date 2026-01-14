# MedAgentBenchmark Green Agent (Assessor)

The **MedAgentBenchmark Green Agent** is the reference implementation of the **Assessor Agent** in the Agentified Agent Assessment (AAA) architecture. It is responsible for orchestrating medical tasks, communicating with the **Purple Agent** (the model being evaluated), and validating the results against a reference solution.

## Architecture

This agent operates within the AAA framework:

1.  **Platform**: Sends an evaluation request to the Green Agent.
2.  **Green Agent (Assessor)**:
    - Receives the request.
    - Retrieves necessary medical data from its internal **FHIR Server**.
    - Formulates instructions and communicates with the **Purple Agent** (Model) via the [A2A (Agent-to-Agent) Protocol](https://a2a-protocol.org/).
    - Evaluates the Purple Agent's response against a ground truth (Reference Solution).
    - Return the evaluation result to the Platform.
3.  **Purple Agent (Model)**: The agent system under test.

### Microservices

The Green Agent runs as a composed service:

- **Green Agent (Python A2A Service)**: Listens on port `9009`. Handles agent logic and communication.
- **FHIR Server (HAPI FHIR)**: Listen on port `8080` (Internal/External). Provides a standardized medical data repository.

## Prerequisites

- **Docker**: For building and running the containerized agent.
- **Python 3.11+**: For local development.
- **Make**: For running automation scripts.
- **uv**: For fast Python dependency management (`pip install uv`).

## Getting Started

### 1. Installation

Install project dependencies using `uv`:

```bash
make install
```

### 2. Local Development

Run the agent locally (requires Python environment setup):

```bash
make dev
```

The agent will start on `http://localhost:9009`.

### 3. Docker Build & Run

Build the production Docker image:

```bash
make build
```

Run the container (maps port 9009, enables host gateway for E2E testing):

```bash
make run-container
```

## Verification

### Unit Tests

Run the test suite using `pytest`:

```bash
make test
```

_Note: Some tests require a running agent instance._

### End-to-End (E2E) Verification

Validate the full agent flow using the E2E verification script. This script mocks a **Purple Agent** and a **Platform**, initiating a task and checking the Green Agent's response.

1.  Start the Green Agent (e.g., in a separate terminal via `make run-container` or `make dev`).
2.  Run the verification:

```bash
make verify
```

## Project Structure

```
.
├── Makefile                # Production-grade build and run commands
├── Dockerfile              # Multi-stage Docker build for Green Agent
├── pyproject.toml          # Python dependencies and configuration
├── start.sh                # Container entrypoint script
├── scripts/
│   └── verify_e2e.py       # E2E verification script (Mock Purple Agent + Platform)
├── src/
│   ├── agent.py            # Main Agent implementation (A2A logic)
│   ├── server.py           # A2A Server setup
│   ├── executor.py         # Task execution logic
│   └── med_data/           # Medical data utilities and reference solutions
└── tests/                  # Unit and conformance tests
```

## API Documentation

The agent exposes the following [A2A Protocol](https://a2a-protocol.org/) endpoints:

- `GET /.well-known/agent-card.json`: Returns the Agent Card metadata (capabilities, description).
- `POST /`: Accepts JSON-RPC 2.0 messages for agent communication.

## License

[MIT](LICENSE)
