package fv.compat;

import com.fasterxml.jackson.core.StreamReadConstraints;

public final class ApalacheJsonLimits {
    public static void main(String[] args) {
        StreamReadConstraints.overrideDefaultStreamReadConstraints(
            StreamReadConstraints.defaults().rebuild().maxStringLength(67_108_864).build()
        );
        at.forsyte.apalache.tla.Tool.main(args);
    }
}
