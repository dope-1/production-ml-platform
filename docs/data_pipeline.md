# Data contracts, splits and reproducibility

Required canonical columns are declared in data/validation.py. All source
measurements must be finite integral numeric values. Missing data, unexpected or
duplicate columns, duplicate IDs, impossible ranges and unknown category codes
fail loudly. Because the source documents no missing values, rejecting nulls is
more appropriate than silently imputing a damaged import. Known undocumented
codes in education (0,5,6), marriage (0) and repayment (-2,0) are retained with
explicit allowed sets; no category is silently mapped. The first two are audit
attributes only. Repayment codes are treated as numeric historical status, a
modeling limitation, not a claim that unknown codes mean a precise duration.

The source zip checksum is pinned; imported canonical CSVs record their own
checksum and provenance. Only a bounded XLS member is read in memory; archives
are never extracted to paths. Prepared dataset versions combine source digest,
split seed, feature schema and split-policy version. Train/validation/test file
checksums are verified on every load. Regenerate a new dataset version instead
of editing processed files. Incomplete versions fail loudly rather than being
silently repaired.

A stable input sort by customer_id precedes StratifiedGroupKFold. Predictor
profile hashes (excluding demographics and target) define groups. This prevents
equal financial profiles leaking across partitions, even with conflicting labels.
IDs and profile hashes are never used as predictors. Fold assignment is seeded,
roughly stratified, and disjoint; exact partition sizes depend on grouping.
Three folds train, one validates, one tests. There are no observation timestamps
sufficient for a rolling split, so temporal validity is not claimed.

Within training, grouped stratified CV refits the complete pipeline in every fold.
StandardScaler exists only in the logistic pipeline and never fits on validation
or test. FinancialFeatures is stateless and rejects wrong input order, target,
unknown columns and non-finite values. Derived ratios are identical during
training and artifact inference. All six parameter trials are logged; the test
partition is scored once for the selected candidate per training invocation.
Repeatedly examining test reports can still cause human selection bias: freeze
this evaluation cohort and do not tune using test feedback. A genuinely new
production dataset requires a fresh prospective evaluation design.

Each run records timestamps, exact source digest, schema version, configuration,
seed, package versions, source-code SHA-256 and Git SHA/dirty state. In an unhosted
archive the Git SHA is honestly `uncommitted`; the code digest still identifies the
source. Models embed the package code in MLflow artifacts. Random seeds and two
CPU threads are fixed; latency and floating-point results can vary by hardware.
