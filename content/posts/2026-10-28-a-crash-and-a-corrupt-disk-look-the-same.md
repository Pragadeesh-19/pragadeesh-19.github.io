---
title: A crash and a corrupt disk look the same
date: 2026-10-28
description: How NodusDB's log tells a power cut from a damaged disk, built from what write and fsync really promise, and what 2,858 simulated crashes did and did not prove.
slug: a-crash-and-a-corrupt-disk-look-the-same
image: /img/og-crash.png
---

*How NodusDB's log tells a power cut from a damaged disk, built from what write and fsync really promise, and what 2,858 simulated crashes did and did not prove.*

Every database log has a last record, and after a crash that record is sometimes half written. Its checksum fails.

So what happened? Maybe the power went and the record was cut short. That is normal. You cut it off and carry on. Or maybe the disk is going bad and has damaged a record you were told was safe. That is not normal. You stop and tell a human.

The bytes can be identical in both cases. The right actions are opposite. If you cut off data that was damaged, you silently lose commits you already promised. If you refuse to start after an ordinary power cut, you have built a database that fails at the one thing a log is for.

This post is how NodusDB tells the two apart. I build the answer from one fact about disks, show the whole rule in a few lines of Java, and then test it against thousands of simulated crashes. While doing that I found a hole in my own test, and I'll show you that too.

## Start with what a write does

When your program calls `write()`, the bytes go into the operating system's page cache, which is ordinary memory. The call returns. Nothing has reached the disk.

`fsync()` is the call that waits until the drive says the bytes are stored. Until it returns, you don't know where your bytes are.

![A diagram with three boxes: your program, the page cache, and the disk. A solid arrow from the program to the page cache is marked "write() returns here, a power cut loses the bytes". A dashed arrow from the page cache to the disk is marked "fsync() returns here, the bytes are on the disk".](/img/crash-writepath.png)

Three things follow from this, and everything else in this post rests on them.

- Writes you haven't forced can be lost.
- They can be lost in any subset. The operating system and the drive write dirty data back in whatever order suits them, so after a power cut a later write can be on the disk while an earlier one is not.
- One write can be cut part-way. A record bigger than a sector can reach the disk in pieces.

This is not a rare corner. A 2014 paper, [All File Systems Are Not Created Equal](https://research.cs.wisc.edu/adsl/Publications/alice-osdi14.html), built a tool called ALICE and used it on eleven widely used systems, including databases and key-value stores. It found 60 crash vulnerabilities: update code that is only correct if the file system behaves in one particular way. The file systems it tested differ in which of those behaviours they allow, so code that survives on one can break on another.

## What the log looks like

NodusDB keeps its changes in an append-only log of typed records. A record looks like this:

```
len u32 | type u8 | flags u8 | reserved u16 | lsn u64 | payload | crc32c
```

Records are 8-byte aligned, and the log is cut into segments of 64 MiB. The `lsn` is a position number that goes up by one for every record. A transaction is its records followed by a commit record, and recovery only ever applies whole transactions.

In `sync` mode a write returns only after its records are forced to disk. Many callers can share one `fsync()`: a flusher thread collects whatever has arrived and forces it together. When a write returns, I call it acknowledged. The database has promised that it will survive.

## What a checksum can and cannot tell you

The CRC at the end of each record answers one question: do these bytes match what was written?

It cannot say why they don't. A record cut short fails the check. A bit flipped by a failing drive fails it. A block of zeros where a record should be fails it. The result is the same and the causes are different, and recovery has to pick an action anyway.

## Two rules that look right

**Rule one: stop at the first bad record and keep everything before it.** This is simple and often good enough. SQLite's write-ahead log works this way. [Its format document](https://www.sqlite.org/walformat.html) says the scan "stops at the end of the file or at the first invalid checksum", and the last valid commit frame decides what is kept. As I read it, a damaged frame in the middle ends the log right there, and the transactions after it are not recovered.

RocksDB shows how real the choice is. It has [four WAL recovery modes](https://javadoc.io/static/org.rocksdb/rocksdbjni/7.9.2/org/rocksdb/WALRecoveryMode.html): one that expects no corruption at all, one that stops at the first inconsistency, one that tolerates a damaged tail, and one that skips any damaged record. A mature database that makes you pick tells me the question is hard.

**Rule two: look at what comes after.** If valid records follow the bad one, it must be corruption. If nothing valid follows, it is a torn tail. It feels clever, and I considered it. I threw it out for two reasons, both from my design notes.

First, after a power cut a later write can persist while an earlier one is lost. A perfectly normal torn tail can contain a hole of zeros and then a good record after it. The scan would call that corruption and refuse to open after an ordinary crash.

Second, the scan reads bytes that users wrote. NodusDB stores names in the log as strings, and a string can hold anything, including bytes shaped like a valid record. A rule that trusts what it finds in the log can be fooled by the data it is protecting. That second reason is my reasoning. I have not built an attack.

## Stop reading the bytes. Ask what you knew.

Here is the move. Recovery doesn't have to guess from the content, because the writer knows something the content can't say: how far it has forced.

When `fsync()` returns, every byte up to that point is on the disk, and a crash cannot tear it. So if the writer remembers that position durably, recovery can use it after a crash:

- A bad record **before** the position can't be explained by a crash. It is corruption. Refuse to open.
- A bad record **at or after** the position might be explained by a crash. Cut the log back to the last whole transaction and carry on.

I call the remembered position the forced mark.

![Two rows of six records with a thick vertical line, the forced mark, after the fourth. In the first row the third record is bad, before the mark: those bytes were forced, so it is corruption and the database refuses to open. In the second row the sixth record is bad, after the mark: it is a torn tail, so the log is cut back to the last whole transaction.](/img/crash-markrule.png)

That rule is the entire decision. This is the real code, with a few long lines broken to fit the page:

```java
private void classifyDamage(Segment segment, long offset, Verdict verdict) {
    if (isBelowMark(segment.base(), offset)) {
        String detail = verdict == Verdict.INCOMPLETE
                ? "the record is cut short" : reader.invalidReason();
        throw corrupt(segment, offset,
                detail + " inside the part of the log known to be durable");
    }
    stopped = true;
}

private boolean isBelowMark(long segmentBase, long offset) {
    return mark != null && mark.isAfter(segmentBase, offset);
}
```

`stopped = true` means "this is the end of the log". Recovery then truncates to the last commit point and deletes any later segments.

### Where the mark lives

The mark has to survive a crash too, and writing it is itself a write that can be torn. So it is a small file with two slots of 32 bytes. Each slot holds a magic number, a sequence number, the segment, the offset, and a CRC32C over those fields. The writer alternates between the slots and forces the file after each write:

```java
void record(long segmentBase, long offset) throws IOException {
    sequence++;
    slot.clear();
    slot.putInt(0, MAGIC).putLong(4, sequence)
            .putLong(12, segmentBase).putLong(20, offset);
    slot.putInt(CHECKSUM_OFFSET, checksum(slot));
    channel.write(slot, (sequence % SLOTS) * SLOT_BYTES);
    channel.force();
}
```

A torn write can damage only the slot being written. The other slot still holds the previous mark, and the reader takes the intact slot with the higher sequence number.

The value of the mark has two rules.

**It must never run ahead of the truth.** The writer moves its in-memory position only after `fsync()` returns, and the mark file is written from that position later. If the mark ran ahead, bytes that never reached the disk would count as known to be durable, and a normal torn tail would look like corruption.

**It may lag.** Rewriting the mark costs another `fsync()`, so by default it is written about every 100 ms, not on every commit. An explicit `force()` and a `close()` write it straight away. Lagging is the safe direction. Bytes that are in fact safe are just treated as "maybe", which gets the weaker answer.

That is a trade, and it has a price. A bit flip inside the last 100 ms of forced data, followed by a crash before the mark catches up, is classed as a torn tail, so the log is cut there. Recovery reports how many bytes it cut, but it does not refuse to open. And if both slots of the mark file are damaged, there is no mark, and every bad record counts as a torn tail. I wrote the first gap down in my design notes as accepted. I think it is the right trade for now. It is still a trade.

## When fsync itself fails

Recovery can't solve one more case. If `fsync()` returns an error, you no longer know what is on the disk. The tempting move is to retry.

On Linux that can be wrong. After a failed write-back, the kernel can mark the dirty pages clean, so a second `fsync()` reports success for data that never reached the disk. That was behind the 2018 PostgreSQL bug, and PostgreSQL now [panics on an fsync failure instead of retrying](https://wiki.postgresql.org/wiki/Fsync_Errors). A 2020 study of ext4, XFS and Btrfs, [Can Applications Recover from fsync Failures?](https://www.usenix.org/conference/atc20/presentation/rebello), found that pages are always marked clean after a failure, and that none of the failure-handling strategies in the five applications it examined was sufficient.

NodusDB never retries. The first failed force poisons the log:

```java
private void fail(Exception cause) {
    synchronized (monitor) {
        failure = new IndeterminateOutcomeException(
                "the write-ahead log failed and its last records may or may not be durable; reopen the graph",
                cause);
        monitor.notifyAll();
    }
}
```

The write that was waiting gets that exception. So does every later append, force and close, until the graph is reopened. Recovery then reads what is actually on the disk and decides. A test, `aFailedForcePoisonsTheLogAndLaterWritesAreRefused`, makes forces fail on a simulated disk and checks all of this.

## How I test it: build the disk a power cut leaves

You can't test this by pulling the plug. It is slow, you can't repeat it, and each pull shows you one outcome. So I wrote a disk that remembers.

The idea is not mine. SQLite's tests use [a virtual file system](https://www.sqlite.org/testing.html) that can "make a snapshot of the entire filesystem after a set number of I/O operations", then revert to it and add "random file damage" of the kind a power loss leaves. TigerBeetle runs [a whole cluster in a simulator](https://docs.tigerbeetle.com/concepts/safety/) and subjects it to network, storage and process faults. Mine is much smaller: one log, one file system.

`SimulatedDisk` stands in for the file system. It records every event: create, write, truncate, force, delete. Then `crashImage(eventsKept, pendingMask, lastWritePrefix)` builds the disk that a crash at that moment could leave:

- Everything up to each file's last force is durable.
- Writes after that are pending, and a bit mask picks which subset of them reached the disk.
- The last write can be cut at any byte prefix.

![A flow of four steps: run a workload on a fake disk that records every write, force and truncate; pick a crash point by keeping only the first N events; build the disk the crash leaves from everything forced, any subset of the pending writes, and the last write cut at byte k; run recovery on that disk. Four checks follow.](/img/crash-crashimage.png)

The workload is 30 operations, a mix of single-tuple writes and batches of one to five tuples, in 2,048-byte segments so the log keeps rolling over to new files. It runs twice. In `sync` mode every write waits for its force. In `async` mode the test forces by hand after every seventh operation and at the end, and only commits covered by a force count as acknowledged.

For every crash point the test builds six images with different subsets of pending writes: none, all, two alternating bit patterns, and two random ones. It adds many more with the last write torn. Then it runs recovery and checks four things:

1. What comes back is a prefix of what was written.
2. Every acknowledged commit is in it.
3. The log takes a new write, and positions keep rising.
4. Reopening again loses and repeats nothing.

| Run | Disk events | Times the mark was forced | Crash images | Result |
|---|---:|---:|---:|---|
| Shipped test, sync | 77 | 3 | 2,068 | pass |
| Shipped test, async | 34 | 7 | 790 | pass |

That is 2,858 simulated power cuts, replayed in about 10 seconds on my laptop. For these two workloads, under this disk model, no crash point loses an acknowledged commit, brings back something that isn't a prefix, or makes recovery refuse a legitimate crash.

## What that does not prove

I'd rather list the gaps myself.

- **Tears are not at every byte.** In the sync run, writes up to 64 bytes are cut at every byte. Larger writes, and the whole async run, are cut at every 13th byte.
- **A write is only cut as a prefix.** A real device can keep a later sector of one write and lose an earlier one. The subset mask covers different writes reaching the disk out of order, not the inside of a single write.
- **Creating and deleting files counts as durable at once.** Real file systems need a directory sync, and the simulator never checks that I do one at the right moments.
- **A drive that lies about `fsync()` is not modelled.**
- **There are no bit flips in these runs.** Separate tests cover that side: flipping a bit inside forced data, cutting a record short inside it, shortening the log to below the mark, and deleting a segment from the middle must each refuse to open.
- **Thirty operations is small.**

## The mark barely moved

The gap that bothered me most I found only by counting. The mark is driven by a timer of about 100 ms, and the simulated workload finishes in a few milliseconds. So I counted how often the mark file was forced during each run. Three times in the sync run: on open, when the writer starts, and on close. Seven times in the async run, which adds my four manual forces.

That means that for all 30 writes of the sync run the mark sat at the very start of the log. Nearly every crash image was testing the torn-tail path. The half of the rule that says "before the mark is corruption" was barely in play.

So I wrote a variant of the same test with the flush and mark intervals set to 1 ms and a 4 ms pause between operations, so that the mark moves while the workload runs.

| Run | Disk events | Times the mark was forced | Crash images | Result |
|---|---:|---:|---:|---|
| Variant, sync | 138 | 33 | 4,354 | pass |
| Variant, async | 61 | 8 | 992 | pass |

With the mark moving, 5,346 more crash images found no failure. The design holds up.

The next question is the one that matters: would the shipped test notice if the mark were wrong? I broke the code on purpose, in a scratch copy. I changed one line so that the mark records where the writer has written, not where it has forced. That is the "ahead of the truth" bug from earlier.

| Test | With the bug |
|---|---|
| The shipped crash test | passes |
| All 2,640 tests in the core module | none about the log fails |
| My variant | fails, in the async run |

In that full run 16 tests failed and 41 were skipped. All 16 failures are tests that call a Python helper script, and my scratch run could not find Python. None of them touches the log.

The failure my variant gave is the one a user would see, a database that refuses to open after an ordinary power cut:

```
CorruptLogException: the log ends at segment 00000000000000000056.nlog
offset 32 but data up to segment 56 offset 72 was known to be durable
```

I also checked the other direction. I made recovery ignore the mark, so that every bad record counts as a torn tail. Both crash tests passed again, the shipped one and my variant. Two targeted tests failed: `damageInsideForcedDataRefusesToOpen` and `aRecordCutShortInsideForcedDataRefusesToOpen`. So the crash test guards one half of the rule, those two tests guard the other half, and nothing guarded the mark running ahead.

So the test I had been quoting was real, and weaker than it looked. A timer-driven feature, exercised by a run that is over before the timer fires, was barely tested. I have pushed the variant to a branch of the repository. The link is at the end.

## What I'd keep from this

**Don't classify damage by looking at the damage.** Remember what you knew when it happened.

**A passing test is only as good as the bugs it can fail on.** Break the code on purpose and see what notices.

**Count what your test exercises.** I trusted the number of crash images. The number that mattered was how many times the mark moved.

## Try it, or help

The test is in the repository, [github.com/Pragadeesh-19/nodusdb](https://github.com/Pragadeesh-19/nodusdb), as `core/src/test/java/io/nodusdb/log/CrashExplorationTest.java`. The moving-mark variant is on the branch [`test/crash-exploration-moving-mark`](https://github.com/Pragadeesh-19/nodusdb/tree/test/crash-exploration-moving-mark). The same branch corrects the README and four guides, which said torn writes are cut at every byte. With JDK 22 or newer and Maven, `mvn -pl core test -Dtest=CrashExplorationTest` runs the test, on main or on that branch. NodusDB is open source under Apache 2.0.

Two questions I would like help with:

- **Have you seen a drive or file system that keeps the later part of a single write and loses the earlier part?** My simulator only cuts a write at a prefix. If you have seen the other kind, I would like to know what it was and how you found it.
- **Is a lazy mark the right trade?** Writing the mark after every group commit closes the 100 ms gap and costs one more `fsync()` per commit. Keeping it lazy is cheaper and leaves the gap. I chose lazy. Tell me if you would choose the other way.

Last time I said the next post would be about writing the log straight into an Iceberg table. It needs this one first: a table built from a log can only be as good as the log. So that is next.
