---
title: Every memory read cost 300 nanoseconds
date: 2026-10-21
description: How a GraalVM native image made my database's writes 40 times slower, why the compiler team had already fixed it, and what I measured when I tried the fix.
slug: every-memory-read-cost-300-nanoseconds
image: /img/og-300ns.png
---

*How a GraalVM native image made my database's writes 40 times slower, why the compiler team had already fixed it, and what I measured when I tried the fix.*

On 20 October I re-ran a benchmark I had stopped looking at. My README said the lake engine in NodusDB ingested 846,137 rows a second. The release sitting on PyPI did 21,017.

Same laptop. Same benchmark. Forty times slower.

This is the story of where those nanoseconds went. It is also the story of a mistake I made before I wrote any of the fix: I didn't check whether someone had already found the problem. Someone had.

## What NodusDB is, in two paragraphs

NodusDB is an embedded database for Python. You `pip install nodusdb` and it runs inside your process, with no server to start. It has two engines. A graph engine holds relationships in memory and answers traversals and permission checks in microseconds. A lake engine takes streaming upserts and writes them out as Parquet files that DuckDB, Spark and PyArrow can read.

The engine is written in Java and compiled ahead of time with GraalVM Native Image into one shared library. Python calls it through `ctypes`. There is no JVM in your process and nothing to install beyond the wheel.

## The change that caused it

In early October I moved the lake's columns out of Java arrays and into native memory, using the `java.lang.foreign` API: `MemorySegment`, arenas, value layouts. I had good reasons. Native memory doesn't move under you, so one day the columns can be handed to Arrow without a copy. The garbage collector has nothing to scan. And I can count every byte against a memory budget and refuse a write before it happens.

Every test passed. On a plain JVM the same Java code still ran an upsert in about 300 ns, so the benchmarks I was watching looked fine. The graph kernel got the same treatment, and its tests passed too.

Then 0.1.0 shipped. On 20 October I rewrote the README and re-ran everything against the wheel people actually install:

| Measure | README said | 0.1.0 measured |
|---|---:|---:|
| Lake ingest, rows a second | 846,137 | 21,017 |
| Flush of 250,000 rows to Parquet | 0.265 s | 9.924 s |
| Sum of 1,000,000 rows in memory | 4.0 ms | 922.6 ms |

The old numbers were real. They described an implementation that no longer existed. I had shipped a release with figures from before the change.

## Rule one: measure the primitive

The tempting move is to start redesigning. Maybe the arenas were wrong. Maybe the scope checks were expensive. Maybe the compiler had regressed.

I ruled out the compiler first. A library I had built on 7 October with an older GraalVM was just as slow. Then I stopped guessing and wrote small programs, each one doing a single thing a million times and built as a native image with the library's own flags.

Here is the cleaned-up version of those probes: [one file with no dependencies](/files/MemorySegmentRead.java) that reads a million longs six ways and prints the cost of one read. I ran it on GraalVM Community Edition 25.0.2, the compiler my wheels are built with, first on the JVM and then as a native image.

| One read, in nanoseconds | JVM | Native image |
|---|---:|---:|
| `MemorySegment.getAtIndex(JAVA_LONG, i)` | 1.8 | 249 |
| `MemorySegment.get(JAVA_LONG_UNALIGNED, offset)` | 2.5 | 287 |
| A `static final VarHandle` from `JAVA_LONG.varHandle()` | 1.9 | 273 |
| `MemorySegment.copy` into a `long[]`, 4,096 at a time | 6.9 | 2.0 |
| `ByteBuffer.asLongBuffer().get(i)` | 1.9 | 6.9 |
| A plain `long[]` | 0.9 | 1.1 |

Reading one long through a `MemorySegment` cost 250 to 290 nanoseconds in the native image. On the JVM it cost about two. (In my first probes, with the library's own build flags, it came out nearer 300, which is where the title comes from.) In those earlier probes it made no difference where the memory came from: an auto arena, a global one, a shared one, a confined one, a raw address, even a segment wrapping a heap array.

Everything that went through an accessor was slow. Everything that moved a block of memory in one go was fine.

That also explained the graph. Its adjacency lives in the same kind of native memory, read through the same calls. A build from 3 October that still kept the graph in Java arrays inserted 1.06 to 1.30 million edges a second. The 0.1.0 wheel did 162,689.

## I went to report it. It was already fixed.

On 21 October I sat down to write the bug report. First I did what I should have done a day earlier: I searched the GraalVM issue tracker.

It was there, twice. [Issue 13825](https://github.com/oracle/graal/issues/13825), closed in June, was titled "scalar MemorySegment.get ~100x slower than HotSpot". [Issue 13377](https://github.com/oracle/graal/issues/13377), still open, measured 111 times. On the second, a GraalVM maintainer had replied that the problem "should already have been fixed" by a pull request, and that the change was "not part of 25.0.2 so far". That is the release my wheels are built with.

So my questions changed. Is it really fixed? In which release? Does my compiler have it? I downloaded the newest Community build, 25.4.4.1.1 from 22 September, and ran the same file on three compilers.

| Compiler | Released | Native image, `getAtIndex` |
|---|---|---:|
| GraalVM CE 25.0.2, the one my wheels use | January 2026 | 249 ns |
| Oracle GraalVM 25.0.4, the long-term-support line | July 2026 | 170 ns |
| GraalVM CE 25.4.4.1.1, an Innovation release | September 2026 | 2.85 ns |

![A bar chart of the cost of one MemorySegment read: 1.8 ns on the JVM, 249 ns in a native image built with CE 25.0.2, 170 ns with Oracle GraalVM 25.0.4 LTS, and 2.85 ns with CE 25.4.4.1.1.](/img/toolchains.png)

The fix works. On the newest build a read costs 2.85 nanoseconds, about 90 times less than on 25.0.2. The long-term-support line has not picked it up: the July Oracle GraalVM LTS is faster than CE 25.0.2 but still about 60 times slower than the fixed build.

I didn't file a bug. A duplicate would only have cost the maintainers time. If you are stuck on the 25.0.x line, the file above and this table are my evidence that it is still affected there.

Why was it slow? The fix is [pull request 13215](https://github.com/oracle/graal/pull/13215), merged on 26 March, and its description explains it. What follows is my plain-English reading of that description, so any mistakes are mine.

On the JVM, the JIT can treat the layout you pass to `get` as a constant, so the `VarHandle` behind it turns into a plain load. Native image does an early optimising pass before that can happen. At that point the layout is just a method parameter. The `VarHandle` also sits behind a lazily filled cache. And `MemorySegment.get` is an interface call with several implementations, which the compiler couldn't resolve to a single method. So no `VarHandle` ever became a load, and every read took the slow, general path. The fix teaches native image to resolve calls on a sealed hierarchy early, and marks `get` and `set` as places where a `VarHandle` access should be turned into a load.

I wish I had read that before I started building. It would have told me where to look, and which compiler to try first.

## What I did about it on 20 October

I did most of the next part before I knew any of this, and I'll tell it as it happened. It still matters, because the 25.0.x line is where many of us are stuck.

### Rule two: a library must not crash its host

The fastest fix was obvious: read through raw pointers and skip the checks. GraalVM's `Pointer.readLong` cost 1.65 ns in my probe.

But NodusDB runs inside someone else's Python process. If my code reads past the end of a buffer, it doesn't fail one query. It reads garbage from somewhere in their process, or takes the whole process down. So the fix had to keep every check: the offset in bounds, the arena still alive, the segment native and writable. A bad access has to throw an exception that the C layer turns into an error code.

I ruled out two other routes. `sun.misc.Unsafe` is on its way out, and using it prints a warning to the user's stderr. Nobody wants a library that writes to their terminal. Bulk copies and buffer views everywhere would make random access slower, and buffer views top out at 2 GB.

### One door into native memory

Every read and write of native memory in NodusDB now goes through one class, `NativeMemory`, with two backends behind the same methods:

```java
public static long getLong(MemorySegment segment, long address, long size, long offset) {
    if (POINTERS && address != NOT_NATIVE) {
        if (offset < 0 || offset > size - Long.BYTES) {
            throw outOfBounds(offset, Long.BYTES, size);
        }
        long value = WordFactory.<Pointer>pointer(address + offset).readLong(0);
        Reference.reachabilityFence(segment);
        return value;
    }
    return Slow.getLong(segment, offset);
}
```

On the JVM, `POINTERS` is false and the call goes to the normal segment accessor, checked by the JDK. In the native library it is a bounds check and a raw read. `reachabilityFence` keeps the segment, and so its memory, alive until the read is done.

`POINTERS` comes from a system property that native image sets both when it builds the image and when the image runs. The native build initializes `NativeMemory` at build time, so the flag becomes a constant and the dead branch disappears. A plain JDK never loads the GraalVM pointer code at all.

![A diagram of NativeMemory: callers pass a segment, address, size and offset to one accessor, which uses the JDK accessor on the JVM and a bounds check plus a pointer read in the native library.](/img/native-memory-design.png)

### Rule three: know what your compiler will inline

My first version of that accessor was correct and still slow. A second finding explained why.

On CE 25.0.2, GraalVM only inlines trivial methods: at most 20 nodes and one call, or 40 nodes for a leaf with no calls. An accessor with a bounds check and a fallback path is never trivial, so every read stays a real function call. How much that call costs depends on what the caller hands it. About 5.7 ns when the caller passes an address and size it has already cached. 20 to 25 ns when the accessor has to ask the segment for its address, size, liveness and kind on every call.

So the owners of memory cache what the accessor needs. Each column keeps its address and size next to its segment and refreshes them when it grows. The graph kernel publishes its chunks as one immutable record of segments, addresses and sizes, so a lock-free reader always sees a consistent set. That also closed a race I hadn't seen: a reader could briefly see a grown chunk array before its new chunk was set.

Loops that walk memory in order don't call the accessor per element at all. They copy 4,096 values at a time into a reused heap array with `MemorySegment.copy` (2 ns a value in the native image) and loop over the array. The Snappy compressor copies each page into a reused `byte[]` once and runs its match finder over plain heap arrays.

### Proving nothing else changed

A faster writer that writes different bytes is a different writer. Before touching anything, I recorded the SHA-256 of every Parquet file the old writer produced: 132,000 rows through both ingest paths, with overwrites, deletes and new keys, under both codecs. A test now writes the same data and compares hashes. Changing one byte in the page sink fails it. The new files are byte-identical to the old ones.

Two more guards keep this from coming back. A test reads the main sources and fails the build if anything but `NativeMemory` touches a segment accessor directly. And an exported function runs the accessor contract (bounds, closed arenas, read-only views, heap segments) inside the compiled library, which the Python suite calls.

## What a fixed compiler is worth

Now the question I couldn't answer on 20 October. If the compiler is fixed, was my workaround wasted? I built five variants and ran them back to back on one laptop in one session, twice each:

1. **0.1.0 as released.** The wheel from PyPI, built with CE 25.0.2.
2. **0.1.0's source on the new compiler.** Only the compiler changes, with CE 25.4.4.1.1.
3. **0.1.1 as released.** My workaround on the old compiler: the wheel from PyPI, CE 25.0.2.
4. **0.1.1's source on the new compiler, with the pointer path switched off.** Plain segment accessors, but every other change I made.
5. **0.1.1's source on the new compiler, as shipped.** My workaround on the fixed compiler.

| Variant | Graph inserts a second | Lake rows a second | Flush, 250,000 rows |
|---|---:|---:|---:|
| 1. 0.1.0, CE 25.0.2 | 166,000 | 51,500 | 13.1 s |
| 2. 0.1.0 code, CE 25.4 | 552,000 | 157,000 | 1.71 s |
| 3. 0.1.1, CE 25.0.2 | 569,000 | 1,608,000 | 0.34 s |
| 4. 0.1.1 code, CE 25.4, pointers off | 520,000 | 662,000 | 0.67 s |
| 5. 0.1.1, CE 25.4 | 691,000 | 2,329,000 | 0.27 s |

One laptop, one session, each variant run twice and averaged. The two runs agreed within about 10 percent. Rows 1 and 3 are the released wheels. Rows 2, 4 and 5 are local builds of the same commits. The graph column is one million inserts through `compare.py`. The lake columns come from `lake_native_probe.py`, one Arrow batch of 250,000 rows, a smaller test than the taxi benchmark above, so its absolute numbers differ. The laptop also ran slower in this session than on the day I fixed it. Compare rows with each other, not with earlier numbers.

Here is what I read from it.

- **For the graph, the compiler fix does most of the work.** Row 2 inserts 552,000 edges a second with no change to my code. My workaround on the old compiler (row 3) reached 569,000.
- **For the lake, it does not.** Row 2 ingests 157,000 rows a second against 1.6 million for my workaround. The scalar accessor is no longer the slow part of that code, but something else is, and I haven't profiled what.
- **On the new compiler, my workaround still pays.** With the pointer path off (row 4), the same code ingests 662,000 rows a second and flushes in 0.67 s. With it on (row 5): 2.3 million and 0.27 s. In the small reproducer plain access costs 2.85 ns, so I don't yet understand why it is still this far behind in the real code.
- **The new compiler makes the workaround faster too.** Row 5 against row 3, same code: 22 percent more graph inserts, 45 percent more ingest, 21 percent less time to flush.

I haven't moved the released wheels to the new compiler. The 25.x Innovation releases move faster than the 25.0.x line, and I have been burned by a compiler change before: a local build with GraalVM CE 23 ran one call about 130 times slower than CE 22, and I wrote down "time a new toolchain before you trust it". So the order is test first, then switch. The whole test suite and the speed gate need to pass on it.

## What I'd tell myself on 20 October

**Search the tracker before you debug, then try the newest release before you design anything.** Ten minutes of searching and a 330 MB download would have told me the problem was known, that it was fixed, and which line of releases had the fix.

**Measure the primitive before you redesign.** A twenty-line program answers in an afternoon what a week of guessing about arenas won't.

**A regression that can't show up on the JVM needs a test that runs the native library, and an alarm you did not calibrate on the broken build.** I did have a speed gate in 0.1.0. I had set its limit at 30, twice the worst ratio I had measured, and what I had measured was the slow build. It passed. The new gate also times the lake and fails above 10. In CI the native library now runs within two times the JVM on every probe.

**A number in a README is a claim.** Re-run it against the artifact people actually install, every release.

## Try it, or help

NodusDB is open source under Apache 2.0, and 0.1.1 is on PyPI for Linux, macOS and Windows.

```sh
pip install nodusdb
```

The full engineering review, with every probe and decision, is in the repository: [github.com/Pragadeesh-19/nodusdb](https://github.com/Pragadeesh-19/nodusdb).

Two questions I would like help with:

- **Where does native image still fall off a cliff when you use memory segments?** With the compiler fixed, the 0.1.0 lake code is still ten times slower than my workaround, and I don't know why. If you know which calls native image still doesn't optimise, I'd like to hear about it.
- **Which compiler line should a library ship on?** The long-term-support line has the bug and a longer life. The Innovation line has the fix and the speed. If you've made this choice for a native library, tell me how you decided.

Next time: why NodusDB writes its database log straight into an Iceberg table, and what that makes possible.

<details>
<summary>The reproducer, MemorySegmentRead.java</summary>

```java
import java.lang.foreign.Arena;
import java.lang.foreign.MemorySegment;
import java.lang.foreign.ValueLayout;
import java.lang.invoke.VarHandle;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.LongBuffer;
import java.util.Arrays;

public final class MemorySegmentRead {

    private static final int LONGS = 1_000_000;
    private static final int ROUNDS = 15;
    private static final int CHUNK = 4096;
    private static final VarHandle LAYOUT_HANDLE = ValueLayout.JAVA_LONG.varHandle();

    private static volatile long sink;

    private interface Variant {
        long run(MemorySegment segment, long[] heap, LongBuffer view, long[] scratch);
    }

    private static long getAtIndex(MemorySegment segment, long[] heap, LongBuffer view, long[] scratch) {
        long sum = 0;
        for (int i = 0; i < LONGS; i++) {
            sum += segment.getAtIndex(ValueLayout.JAVA_LONG, i);
        }
        return sum;
    }

    private static long getUnaligned(MemorySegment segment, long[] heap, LongBuffer view, long[] scratch) {
        long sum = 0;
        for (int i = 0; i < LONGS; i++) {
            sum += segment.get(ValueLayout.JAVA_LONG_UNALIGNED, (long) i * Long.BYTES);
        }
        return sum;
    }

    private static long layoutVarHandle(MemorySegment segment, long[] heap, LongBuffer view, long[] scratch) {
        long sum = 0;
        for (int i = 0; i < LONGS; i++) {
            sum += (long) LAYOUT_HANDLE.get(segment, (long) i * Long.BYTES);
        }
        return sum;
    }

    private static long bulkCopy(MemorySegment segment, long[] heap, LongBuffer view, long[] scratch) {
        long sum = 0;
        for (int base = 0; base < LONGS; base += CHUNK) {
            int count = Math.min(CHUNK, LONGS - base);
            MemorySegment.copy(segment, ValueLayout.JAVA_LONG, (long) base * Long.BYTES, scratch, 0, count);
            for (int i = 0; i < count; i++) {
                sum += scratch[i];
            }
        }
        return sum;
    }

    private static long byteBufferView(MemorySegment segment, long[] heap, LongBuffer view, long[] scratch) {
        long sum = 0;
        for (int i = 0; i < LONGS; i++) {
            sum += view.get(i);
        }
        return sum;
    }

    private static long heapArray(MemorySegment segment, long[] heap, LongBuffer view, long[] scratch) {
        long sum = 0;
        for (int i = 0; i < LONGS; i++) {
            sum += heap[i];
        }
        return sum;
    }

    public static void main(String[] args) {
        long expected = 0;
        long[] heap = new long[LONGS];
        for (int i = 0; i < LONGS; i++) {
            heap[i] = (long) i * 0x9E3779B97F4A7C15L;
            expected += heap[i];
        }
        long[] scratch = new long[CHUNK];

        String[] names = {
            "MemorySegment.getAtIndex(JAVA_LONG, i)",
            "MemorySegment.get(JAVA_LONG_UNALIGNED, offset)",
            "static final VarHandle from JAVA_LONG.varHandle()",
            "MemorySegment.copy into long[] (4096 per call), then sum",
            "ByteBuffer.asLongBuffer().get(i)",
            "long[] (control)"
        };
        Variant[] variants = {
            MemorySegmentRead::getAtIndex,
            MemorySegmentRead::getUnaligned,
            MemorySegmentRead::layoutVarHandle,
            MemorySegmentRead::bulkCopy,
            MemorySegmentRead::byteBufferView,
            MemorySegmentRead::heapArray
        };

        System.out.println("java.vm.name = " + System.getProperty("java.vm.name"));
        System.out.println("java.version = " + System.getProperty("java.version"));
        System.out.println("imagecode    = " + System.getProperty("org.graalvm.nativeimage.imagecode"));
        System.out.println("longs per pass = " + LONGS + ", rounds = " + ROUNDS);
        System.out.println();

        boolean ok = true;
        try (Arena arena = Arena.ofConfined()) {
            MemorySegment segment = arena.allocate((long) LONGS * Long.BYTES, Long.BYTES);
            MemorySegment.copy(heap, 0, segment, ValueLayout.JAVA_LONG, 0, LONGS);
            ByteBuffer buffer = segment.asByteBuffer().order(ByteOrder.nativeOrder());
            LongBuffer view = buffer.asLongBuffer();

            for (int v = 0; v < variants.length; v++) {
                long[] nanos = new long[ROUNDS];
                for (int round = 0; round < ROUNDS; round++) {
                    long start = System.nanoTime();
                    long result = variants[v].run(segment, heap, view, scratch);
                    nanos[round] = System.nanoTime() - start;
                    sink = result;
                    if (result != expected) {
                        ok = false;
                    }
                }
                Arrays.sort(nanos);
                double min = nanos[0] / (double) LONGS;
                double median = nanos[ROUNDS / 2] / (double) LONGS;
                System.out.printf("%-58s min %8.2f ns   median %8.2f ns%n", names[v], min, median);
            }
        }
        System.out.println();
        System.out.println(ok ? "all variants returned the expected sum" : "MISMATCH: a variant returned a wrong sum");
        if (!ok) {
            System.exit(1);
        }
    }
}
```

How to run it:

```sh
javac -d out MemorySegmentRead.java
java --enable-native-access=ALL-UNNAMED -cp out MemorySegmentRead
native-image --no-fallback -cp out -o msread MemorySegmentRead
./msread
```

</details>
