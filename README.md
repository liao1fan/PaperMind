# Paper Notion Agent

An intelligent research paper management system that extracts papers from Xiaohongshu posts, generates summaries, extracts figures, and organizes everything into a Notion knowledge base.

## Quick Start

### 1. Install PDFFigures2 (Figure Extraction)

PDFFigures2 extracts figures and tables from PDF papers with high quality.

**macOS (Homebrew):**
```bash
# Install OpenJDK 11 (required by PDFFigures2)
brew install openjdk@11

# Add Java to PATH (choose one based on your shell)
# For zsh (macOS default):
echo 'export PATH="/opt/homebrew/opt/openjdk@11/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# For bash:
echo 'export PATH="/opt/homebrew/opt/openjdk@11/bin:$PATH"' >> ~/.bash_profile
source ~/.bash_profile

# Verify installation
java -version  # Should show "openjdk version 11.x.x"
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install openjdk-11-jdk
java -version
```

### 2. Clone Repository & Setup Environment

```bash
# Clone and enter directory
git clone <repo-url>
cd spec-paper-notion-agent

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:
- **OPENAI_API_KEY**: Your OpenAI API key
- **OPENAI_BASE_URL**: API endpoint (default: https://ai.devtool.tech/proxy/v1)
- **XHS_COOKIES**: Xiaohongshu session cookies (for fetching posts)
- **NOTION_TOKEN**: Notion Integration token
- **NOTION_DATABASE_ID**: Notion database ID
- **LOG_LEVEL**: Logging level (default: INFO)

### 4. Run Agent

```bash
python chat.py
```

Then provide a link (Xiaohongshu URL, arXiv link, or PDF URL) to process a paper.

## How It Works

### Architecture

```
┌─────────────────────────────────────┐
│  User Input (Link)                  │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  Paper Agent (Router)               │
│  - Identify link type               │
│  - Route to digest_agent            │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  Digest Agent (Core Processing)     │
├─────────────────────────────────────┤
│  1. Fetch XHS Post / Download PDF   │
│  2. Extract Paper Metadata (LLM)    │
│  3. Extract Figures (PDFFigures2)   │
│  4. Generate Summary (LLM)          │
│  5. Save to Notion                  │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  Notion Database                    │
│  - Paper Metadata                   │
│  - Summary with Figures             │
│  - Extracted Captions               │
└─────────────────────────────────────┘
```

### Figure Extraction Pipeline

**PDFFigures2 Integration** (`src/services/pdf_figure_extractor_v2.py`):

```
PDF Input
  │
  ├─→ [PDFFigures2] Extract figures with high quality
  │   ├─ Standard figures with bounding boxes → Save PNG (300 DPI)
  │   └─ Regionless captions → Python density detection → Save PNG
  │
  ├─→ [Filter] Remove appendix figures (after References section)
  │
  ├─→ [Metadata] Generate extraction metadata
  │   └─ filename, page, caption, bbox, figure type, source
  │
  └─→ [Output] Organized figures folder
      ├─ Figure1.png, Figure2.png, ...
      ├─ Table1.png, Table2.png, ...
      └─ extraction_metadata.json
```

**Key Features:**
- **High Quality**: 300 DPI PNG output (same as academic standards)
- **Robust**: PDFFigures2 + Python fallback for regionless captions
- **Smart Filtering**: Automatically excludes appendix figures
- **Bilingual Captions**: English + Chinese translations in notes

## Project Structure

```
spec-paper-notion-agent/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── .env.example                 # Configuration template
├── pdffigures2/                 # PDFFigures2 Java tool
│   └── pdffigures2.jar          # Figure extraction engine
├── paper_agents.py              # Main agent definition
├── chat.py                      # Interactive CLI
├── init_model.py                # LLM configuration
├── web_server.py                # Web interface
│
├── src/
│   ├── models/
│   │   └── post.py              # XHS post entity
│   │
│   ├── services/
│   │   ├── paper_digest.py      # Core digest agent
│   │   ├── pdf_figure_extractor_v2.py  # Figure extraction
│   │   ├── xiaohongshu.py       # XHS client
│   │   └── notion_markdown_converter.py
│   │
│   ├── utils/
│   │   ├── logger.py            # Structured logging (structlog)
│   │   └── retry.py             # Retry utilities
│   │
│   └── auth/
│       └── auth_config.py       # Authentication (login system)
│
├── paper_digest/                # Generated outputs
│   ├── pdfs/                    # Downloaded PDFs
│   ├── figures/                 # Extracted figures
│   └── outputs/                 # Generated summaries
│
└── data/
    ├── schedule_tasks.db        # Scheduled tasks
    └── processing_records.db    # Processing history
```

## Features

### Supported Input Formats
- **Xiaohongshu** (小红书): Extract paper links from posts
- **arXiv**: Direct arXiv abstract or PDF URLs
- **PDF**: Direct PDF URLs or local file paths

### Paper Processing Pipeline
1. **Metadata Extraction** (LLM): Title, authors, abstract, keywords, venue
2. **Figure Extraction** (PDFFigures2): High-quality figure/table extraction
3. **Summary Generation** (LLM): Bilingual summaries with figure references
4. **Notion Integration**: Organized database with full metadata and figures

### Smart Features
- Automatic paper deduplication
- Venue field extraction from arXiv metadata
- Bilingual captions (English + Chinese)
- Natural image references in notes
- Processing history tracking

## Troubleshooting

### PDFFigures2 Errors

**Error:** `java: command not found`
```bash
# Verify Java is installed
java -version

# If not installed:
brew install openjdk@11

# Add to PATH:
echo 'export PATH="/opt/homebrew/opt/openjdk@11/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Error:** `pdffigures2.jar not found`
- Verify `pdffigures2/pdffigures2/pdffigures2.jar` exists
- Ensure you're running from the project root directory

**Error:** `java.lang.OutOfMemoryError`
- PDFFigures2 needs ~512MB-1GB RAM for large PDFs
- Ensure your system has sufficient memory

### Configuration Issues

**Notion Connection Failed:**
- Verify NOTION_TOKEN starts with `ntn_`
- Ensure the Integration is connected to your database
- Check NOTION_DATABASE_ID is correct (no spaces)

**Xiaohongshu Cookie Expired:**
- Update XHS_COOKIES in `.env`
- Get fresh cookies from browser DevTools (Network tab)

### Performance Tips

- **Faster processing**: Set LOG_LEVEL="WARNING" to reduce I/O
- **Memory optimization**: Process one PDF at a time
- **PDFFigures2 speed**: Increase DPI slightly reduces quality but improves speed

## API Reference

### Core Functions

**Extract and save paper:**
```python
from paper_agents import paper_agent

# Via agent interface
result = await paper_agent.execute("https://arxiv.org/pdf/2503.08026.pdf")
```

**Extract figures directly:**
```python
from src.services.pdf_figure_extractor_v2 import extract_pdf_figures

figures, blocks = extract_pdf_figures("paper.pdf", output_dir="./figures")
# figures: List[Dict] with filename, caption, page, bbox, etc.
```

**Generate paper digest:**
```python
from src.services.paper_digest import digest_agent

# Via digest_agent (handles full pipeline)
result = await digest_agent.execute("paper_title", pdf_path, metadata)
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `OPENAI_BASE_URL` | API endpoint | Required |
| `XHS_COOKIES` | Xiaohongshu session | Required |
| `NOTION_TOKEN` | Notion integration token | Required |
| `NOTION_DATABASE_ID` | Target database ID | Required |
| `LOG_LEVEL` | Logging level | INFO |
| `LOG_DIR` | Log file directory | ./logs |

## Technology Stack

- **Runtime**: Python 3.11+
- **AI**: OpenAI Agents SDK + GPT-4
- **Figure Extraction**: PDFFigures2 (Java)
- **Database**: Notion API
- **Logging**: structlog (JSON structured logs)
- **HTTP**: httpx (async)
- **PDF Processing**: PyMuPDF (fitz)

## Development

### Adding New Figure Extraction Methods

Extend `PDFFigureExtractorV2` in `src/services/pdf_figure_extractor_v2.py`:

```python
def _my_custom_extractor(self, pdf_path: str) -> List[Dict]:
    """Your extraction logic here"""
    return figures
```

### Customizing Paper Digest

Edit prompts in `src/services/paper_digest.py`:
- Line 1043-1058: Caption format requirements
- Line 1119-1140: Image reference phrases
- Line 1185-1196: Notion block generation

## License

See LICENSE file for details.

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review log files in `./logs/`
3. Enable DEBUG logging in `.env` for detailed output
