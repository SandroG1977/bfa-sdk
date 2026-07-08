# Contributing to Backend for Agents SDK (BFA)

First of all, thank you for taking the time to contribute! We want to make it as easy and transparent as possible for anyone to help expand the BFA pattern.

Special welcome to **Michael Douglas** and the Alura community! This project exists to build upon the ideas introduced in the training courses and scale them to production-grade applications.

---

## Code of Conduct

By participating in this project, you agree to maintain a respectful, welcoming, and collaborative environment.

---

## How Can I Contribute?

### 1. Reporting Bugs
* Check the current Issues tab to see if the bug has already been reported.
* Open a new issue with a clear title, description, steps to reproduce, and environment details (Python version, OS, etc.).

### 2. Suggesting Enhancements
* Open an issue explaining the proposed feature and why it would be beneficial (e.g., adding a new vector database provider like ChromaDB or Qdrant, or new cloud embedders).

### 3. Submitting Pull Requests (PRs)
* Fork the repository and create your branch from `main`.
* If you've added code that should be tested, please add tests or update the mock example in `examples/run_demo.py`.
* Ensure your code formatting aligns with PEP 8 standards.
* Write descriptive commit messages and open a PR targeting the `main` branch.

---

## Core Guidelines & Architectural Principles

To maintain a clean and reliable SDK, all contributions must adhere to the following principles:

1. **Keep the Core Generic:** The core SDK (`bfa_sdk/`) must remain entirely independent of specific business logic (no banking or hotel-specific code in the core). Business logic belongs in the `examples/` or downstream implementations.
2. **Respect the Abstractions:** 
   - New Agents must inherit from `BFAAgent` to ensure automatic compatibility with A2A cards.
   - New MCP tools must be registered via `BFAMCP` to guarantee proper metadata extraction for semantic routing.
3. **Optimized for Serverless:** Keep dependency footprint light to ensure fast AWS Lambda execution. Any heavyweight dependency (like `sentence-transformers` / `torch`) must remain optional.

---

## Translation / Multilingual Docs
This project supports English, Portuguese, and Spanish documentation. If you update the documentation or add new parameters:
* Please update `README.md` (English), `README.pt.md` (Portuguese), and `README.es.md` (Spanish) if possible, or open an issue so others can help translate it.
