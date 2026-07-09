# Illustration-style training set (the designer's hand-rendered plates)

Her actual gouache-and-pencil design plates. These train the LoRA to render
in her ILLUSTRATION hand — NOT used as an inference anchor (jewelry design is
unlimited; anchoring on a few custom pieces would drag every output toward
these specific motifs). Training teaches the hand diffusely; anchoring would
overfit the pieces.

- Distinct from `data/train/bootstrap/` (photoreal generated renders).
- A style LoRA wants ~15-30; these three are the seed. Add more approved
  plates as they accrue, then train per docs/evals/LORA_RUNBOOK.md.
- Prep before training: crop each to just the rendered jewelry (drop the
  figure croquis and blank paper, which are noise).
