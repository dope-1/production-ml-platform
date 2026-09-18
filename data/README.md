# Dataset provenance

Yeh, I. (2009). *Default of Credit Card Clients*. UCI Machine Learning Repository.
DOI: https://doi.org/10.24432/C55S3H
Source: https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients
License: Creative Commons Attribution 4.0 International (CC BY 4.0),
https://creativecommons.org/licenses/by/4.0/

The included raw `uci-default.zip` is the unmodified UCI archive. Its SHA-256 is
recorded in configs/dataset.json. This dataset's license is distinct from the
project's MIT source-code license. The pipeline renames source columns, excludes
demographic attributes from model inputs, derives financial ratios and partitions
records; those transformations are changes made by this project.

Raw archive is approximately 5.5 MB and can also be downloaded by the prepare CLI.
Raw and processed data are gitignored. Source observations concern 2005 Taiwan
credit-card clients; results are not evidence of present-day UAE credit risk.
The dataset does not contain the hypothetical income/employment columns from the
initial project brief; no such columns are fabricated.
