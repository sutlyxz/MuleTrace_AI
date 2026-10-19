# MuleTrace AI

## About the Project

MuleTrace AI is a team project exploring how AI-assisted tools can help investigators review suspicious transaction patterns and trace money flows between accounts.

The system is intended to support investigation and evidence review. Risk indicators are not proof of criminal activity, and final decisions must remain with human investigators.

## Project Goals

- Work with synthetic transaction data during development and testing.
- Trace money flows between accounts.
- Identify suspicious patterns using transparent investigation rules.
- Present investigation findings in a dashboard.
- Explore AI-assisted summaries of investigation results.

## Project Structure

```text
MuleTrace_AI/
├── data/             # Synthetic data and sample datasets
├── investigation/    # Transaction tracing and risk analysis
├── ui/               # User interface and dashboard
├── aws/              # AWS and AI integration
├── tests/             # Automated tests
├── docs/              # Project documentation
├── generate_data.py   # Data generation script
├── README.md
└── .gitignore
```

## Team Responsibilities

- AI / AWS: AI-assisted investigation summaries and AWS integration.
- UI: Dashboard and investigation result visualization.
- Data / Investigation: Synthetic data, transaction tracing, and transparent risk rules.
- Integration / QA: Integration, testing, coordination, and demo preparation.

## Development Principles

- Use synthetic data for development and demonstrations.
- Never commit passwords, API keys, AWS credentials, access tokens, or sensitive personal data.
- Work on a separate branch for each task.
- Review changes before merging them into `main`.
- Treat risk scores as investigation aids, not proof of wrongdoing.

## Getting Started

1. Install Git and Python.
2. Clone this repository.
3. Read the project documentation in `docs/`.
4. Follow the setup instructions agreed on by the team.
5. Run tests before submitting changes.

Setup commands and dependencies will be documented once the team confirms the project's Python environment and libraries.