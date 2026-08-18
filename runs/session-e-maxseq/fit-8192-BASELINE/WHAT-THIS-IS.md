# This is the 8192 BASELINE, and it was very nearly mislabelled as the treatment

Written to `fit-1024/` and renamed. `score_longmemeval.py` drives
`target/release/marlowe.exe --eval-adapter`, and that binary was built at **17:29:28** while
`MAX_SEQ_LEN` changed in the source at **18:44:29**. The run executed at 18:47-18:54, against a
binary **75 minutes older than the change**.

So it measures `MAX_SEQ_LEN = 8192`. The source said 1024, the artifact said 8192, and the directory
name said 1024 - the same shape as a persona test passing while the deployed daemon served a
pre-persona binary. **A source edit is not a deployed change**, and `cargo run --example` does not
rebuild `marlowe.exe`.

Session-level top-1 over the 242 fit queries: **218 hit / 24 miss = 0.9008**.

Kept deliberately rather than deleted: it is a correctly-measured control on the same machine, in
the same session, minutes from the treatment. That is worth more than the recorded 0.7555, which was
taken on a different day under a different configuration.
