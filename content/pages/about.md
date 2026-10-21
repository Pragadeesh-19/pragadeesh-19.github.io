---
title: About
description: Who writes this blog, and what NodusDB is.
---

I'm Pragadeesh, and I live in London. I like problems where the textbook answer is "add another server", because that is usually where the interesting answer is hiding.

## What I'm building

[NodusDB](https://github.com/Pragadeesh-19/nodusdb) is an embedded database for Python. You `pip install nodusdb` and it runs inside your process, with no server and no JVM to install. It holds live state in memory, so a read costs microseconds. Every change goes into one ordered log, and that log is shipped to object storage as a signed chain and as an Iceberg table, so replicas, history and analytics all come from the same place.

The engine is written in Java, compiled with GraalVM Native Image into one shared library, and the only dependency it has is the JDK. It is open source under the Apache License 2.0. Every design decision is written down in the repository with its reason, and the essays here are the longer versions of those notes.

## Where I come from

I studied for a master's in Advanced Computer Science at the University of Leeds. During the course I was the founding tech and workflow intern at Scrubbing Squad, a pre-revenue startup. After that I was a research assistant at the Centre for Human-Inspired AI (CHIA) at the University of Cambridge, where I built a multimodal data ingestion pipeline that turns raw material from under-resourced languages into ML-ready datasets. Its beta is live and is working on Quechua languages.

Then I started NodusDB.

## Get in touch

The best place is [GitHub Discussions](https://github.com/Pragadeesh-19/nodusdb/discussions). If you hit a problem, open an [issue](https://github.com/Pragadeesh-19/nodusdb/issues). If you want to build something hard on top of a fast, honest database core, the open problems are listed in [`TODOS.md`](https://github.com/Pragadeesh-19/nodusdb/blob/main/TODOS.md).
