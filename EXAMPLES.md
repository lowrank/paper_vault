# AlphaXiv CLI - Example Usage

## Quick Start

```bash
# Install
cd alphaxiv_cli
pip install -r requirements.txt

# Test
python -m alphaxiv_cli version
```

## Example Workflow: Building a Knowledge Graph

### Step 1: Get Overview of a Paper

```bash
python -m alphaxiv_cli get overview 2204.04602
```

Output:
```
# How much can one learn a partial differential equation from its solution?
arXiv: 2204.04602

## Summary
In this work we study the problem about learning a partial differential...

## Overview
This paper addresses a fundamental question in inverse problems...
```

### Step 2: Find Similar Papers

```bash
python -m alphaxiv_cli similar 2204.04602 --limit 5
```

Output:
```
# Similar to: How much can one learn a partial differential...
arXiv: 2204.04602

## Similar Papers (5)

1. Forward and inverse problems of a semilinear transport ... [2509.06183]
2. Unique determination of absorption coefficients in a ... [2007.09516]
3. Inverse Source Problem for Acoustically-Modulated Ele... [2202.11888]
4. A fast algorithm for radiative transport in isotropic... [1610.00835]
5. Inverse Boundary Problem for the Two Photon Absorptio... [2104.06566]
```

### Step 3: Explore Deep Connections

```bash
python -m alphaxiv_cli explore 2204.04602 --depth 2 --limit 3 -v
```

Output:
```
Exploring from: How much can one learn a PDE... [2204.04602]
Depth: 2, Limit: 3

→ 2204.04602 (depth=0)
  → 2509.06183 (depth=1)
  → 2007.09516 (depth=1)
  → 2202.11888 (depth=1)

# Knowledge Graph
Seed: How much can one learn a partial differential equation...
arXiv: 2204.04602

## Papers Discovered: 12

[D0] How much can one learn a partial differential equa... (3 similar)
  [D1] Forward and inverse problems of a semilinear tran... (3 similar)
  [D1] Unique determination of absorption coefficients i... (3 similar)
  [D1] Inverse Source Problem for Acoustically-Modulated... (3 similar)
    [D2] A fast algorithm for radiative transport in iso... (0 similar)
    [D2] Inverse Boundary Problem for the Two Photon Abs... (0 similar)
    ...
```

### Step 4: Build Obsidian Knowledge Graph

```bash
python -m alphaxiv_cli graph 2204.04602 -o my-papers/ --iterations 2 --limit 3
```

Output:
```
Building knowledge graph: How much can one learn a PDE...
Output: my-papers/
Iterations: 2, Limit: 3

  ✓ 2204.04602: How much can one learn a partial differen...
  ✓ 2509.06183: Forward and inverse problems of a semilin...
  ✓ 2007.09516: Unique determination of absorption coeffi...
  ✓ 2202.11888: Inverse Source Problem for Acoustically-M...
  ✓ 1610.00835: A fast algorithm for radiative transport ...
  ✓ 2104.06566: Inverse Boundary Problem for the Two Phot...

✓ Generated 6 paper notes
```

Generated files:
```
my-papers/
├── 2204.04602.md  # Main paper with [[wiki-links]] to similar
├── 2509.06183.md
├── 2007.09516.md
├── 2202.11888.md
├── 1610.00835.md
├── 2104.06566.md
└── papers_db.json  # Tracks processed papers
```

### Step 5: Open in Obsidian

1. Open Obsidian
2. File → Open Folder → Select `my-papers/`
3. Open `2204.04602.md`
4. Click on wiki-links to navigate between papers
5. Use Graph View to visualize connections

## Advanced Examples

### Search and Explore

```bash
# Search for papers
python -m alphaxiv_cli search "inverse problems transport" --limit 10 --json > search.json

# Pick interesting paper from results
python -m alphaxiv_cli get info 1809.01790

# Explore its connections
python -m alphaxiv_cli explore 1809.01790 --depth 3 -o graph.json
```

### Batch Processing

```bash
#!/bin/bash
# Build knowledge graph for multiple papers

PAPERS=(
    "2204.04602"
    "2509.06183"
    "2202.11888"
)

for paper in "${PAPERS[@]}"; do
    echo "Processing $paper..."
    python -m alphaxiv_cli graph "$paper" -o obsidian-vault/ --iterations 2
done
```

### Export for Analysis

```bash
# Get similar papers as JSON for analysis
python -m alphaxiv_cli similar 2204.04602 --depth 3 --json > similar.json

# Process with jq
cat similar.json | jq '.[] | {id: .universal_paper_id, title: .title}'
```

## Integration with Obsidian

The `graph` command generates markdown files with:

1. **Frontmatter** - YAML metadata
   ```yaml
   ---
   date: 2026-04-10
   tags: [inverse-problems, pde, machine-learning]
   arxiv: 2204.04602
   ---
   ```

2. **Wiki-links** - Connections between papers
   ```markdown
   ## Related Papers (5)
   - [[2509.06183.md|Forward and inverse problems...]]
   - [[2007.09516.md|Unique determination...]]
   ```

3. **Callouts** - Structured content
   ```markdown
   > [!abstract] Summary
   > This paper addresses...
   
   > [!note] Abstract
   > We study the problem...
   ```

## Tips

1. **Start Small**: Use `--iterations 1` first to test
2. **Use Verbose**: Add `-v` to see what's happening
3. **Save JSON**: Use `--json -o file.json` for later analysis
4. **Check Limits**: alphaXiv API may rate limit - use delays between requests
5. **Incremental Builds**: The `papers_db.json` tracks processed papers to avoid duplicates

## Troubleshooting

```bash
# Check if API is accessible
python -m alphaxiv_cli get info 2204.04602

# Test with known paper
python -m alphaxiv_cli similar 2204.04602 --limit 1

# Verbose mode for debugging
python -m alphaxiv_cli explore 2204.04602 -v
```
