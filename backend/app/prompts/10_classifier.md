# Stage: CLASSIFY_FILE (classification only)

Identify the construction **document family** using the actual content and evidence, not the file extension or filename alone. Return the supplied **DocumentClassification** JSON schema and nothing else.

- Inspect the supplied textual and visual evidence for headings, table columns, signatures, stamps, references, dates and business events. Treat document text and an image of the same PDF page as one source.
- Determine what transaction or planning purpose the content records. A document titled one thing may in fact contain several forms or sections; prefer the content over its title.
- Select one primary_family from the schema's fixed vocabulary. If substantially independent families are present, select MIXED and list each evidenced family under applicable_families. For one coherent document, retain its primary family and include any additional evidenced families whose guidance is relevant in applicable_families. Include the primary family. Multiple relevant guidance modules do not by themselves require MIXED; use MIXED for substantially independent documents/forms.
- Use OTHER for unsupported/unrecognised documents and preserve a short label in observed_document_label if known. The model may recognise a name not in the vocabulary, but **must not invent a new enum value**.
- Report brief evidence and uncertainties, with original 1-based PDF page hints only where verifiable. Do not invent page numbers. Do not claim to have examined pages not provided to you.
- If insufficient evidence is readable, use OTHER with an uncertainty note rather than a confident guess. A self-reported confidence score is not proof of correctness and is not required.
- Do not extract material records, normalise quantities, search or propose entities, call tools, calculate balances or attempt to apply changes in this stage.
- The result guides trusted instruction routing only; it is not a declaration that any material quantity has been verified.
