#pragma once
#include <stdint.h>
#ifdef _WIN32
#define AF_HEIGHT_API extern "C" __declspec(dllexport)
#else
#define AF_HEIGHT_API extern "C" __attribute__((visibility("default")))
#endif
struct AF_HeightReport {
    int32_t status, iterations, samples, pinned, skipped_triangles;
    double total_ms, solve_ms, violation, stationarity, complementarity, max_change, complementarity_relative, objective;
    char message[512];
};
AF_HEIGHT_API int af_height_version();
// World-space snapshots. Faces retain their original identity; no proximity welding.
// Output is untouched on any error. The caller owns all buffers for this synchronous call.
AF_HEIGHT_API int af_height_smooth(const double* base, const double* own, int count,
    const int64_t* faces, int face_count, int columns, const int64_t* parts, int part,
    double radius, double strength, double max_change, double* output, AF_HeightReport* report);
