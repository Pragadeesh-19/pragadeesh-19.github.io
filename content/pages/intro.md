NodusDB is an embedded database for Python. You install it with `pip install nodusdb` and it runs inside your process, with no server to set up. It keeps its state in memory, so reads take microseconds, and it can ship its log to an S3 bucket, where the same log is also an Iceberg table. It is open source under the Apache License 2.0.

I'm Pragadeesh. I write here about how it works and what goes wrong while I build it.
