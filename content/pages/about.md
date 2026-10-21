---
title: About
description: Who writes this blog, and what NodusDB is.
---

I'm Pragadeesh, and I live in London.

## What I'm building

[NodusDB](https://github.com/Pragadeesh-19/nodusdb) is an embedded database for Python. You install it with `pip install nodusdb` and it runs inside your process, with no server and no JVM to install. It holds its state in memory, so a read takes microseconds. Every change goes into one ordered log. The log can be shipped to object storage as a signed chain, and the same log is written out as an Iceberg table, so replicas, history and analytics all read from it.

The engine is written in Java and compiled with GraalVM Native Image into one shared library. Its only dependency is the JDK. It is open source under the Apache License 2.0, and every design decision is written down in the repository with its reason.

## Background

I studied for a master's in Advanced Computer Science at the University of Leeds. During the course I was the founding tech and workflow intern at Scrubbing Squad, a pre-revenue startup. After that I was a research assistant at the Centre for Human-Inspired AI (CHIA) at the University of Cambridge, where I built a multimodal data ingestion pipeline that turns raw material from under-resourced languages into ML-ready datasets. Its beta is live and is working on Quechua languages.

Then I started NodusDB.

## Contact

Open an [issue](https://github.com/Pragadeesh-19/nodusdb/issues) on the repository, or look at [`TODOS.md`](https://github.com/Pragadeesh-19/nodusdb/blob/main/TODOS.md) for the open problems.
