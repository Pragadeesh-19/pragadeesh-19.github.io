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
