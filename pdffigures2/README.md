# PDFFigures2

This directory contains the PDFFigures2 tool for extracting figures and tables from PDF files.

## What is PDFFigures2?

PDFFigures2 is a Scala-based tool that extracts figures, tables, and captions from research papers (PDF format).

- GitHub: https://github.com/allenai/pdffigures2
- License: Apache 2.0

## Installation

```bash
# Clone the repository
git clone https://github.com/allenai/pdffigures2.git
cd pdffigures2

# Build (requires Java 11+ and sbt)
sbt assembly

# The JAR will be at: target/scala-2.12/pdffigures2-assembly-0.1.0.jar
```

## Usage

```bash
# Extract figures from a PDF
java -jar pdffigures2/pdffigures2.jar /path/to/paper.pdf -o /output/directory/
```

## Requirements

- Java 11 or higher
- sbt (Scala Build Tool) - only needed for building from source

## Notes

- This tool is used by `src/services/pdf_figure_extractor_v2.py` for high-quality figure extraction
- The source code is cloned locally but NOT committed to this repository
- See `.gitignore` for excluded files
