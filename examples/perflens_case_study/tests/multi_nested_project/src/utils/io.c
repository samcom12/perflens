#include <stdio.h>
#include <stddef.h>

/*
 * CASE-07: I/O inside loop
 *
 * Intentionally writes one element at a time so the static scanner
 * has a controlled I/O-in-loop case.
 */
int write_field_elementwise(const char *filename,
                            const double *data,
                            size_t n)
{
    FILE *fp = fopen(filename, "wb");

    if (fp == NULL) {
        return -1;
    }

    for (size_t i = 0; i < n; ++i) {
        if (fwrite(&data[i], sizeof(double), 1, fp) != 1) {
            fclose(fp);
            return -1;
        }
    }

    fclose(fp);
    return 0;
}

/*
 * CASE-08: Buffered I/O
 *
 * This provides a less pathological reference implementation for
 * comparison with the element-wise version.
 */
int write_field_buffered(const char *filename,
                         const double *data,
                         size_t n)
{
    FILE *fp = fopen(filename, "wb");

    if (fp == NULL) {
        return -1;
    }

    size_t written = fwrite(data, sizeof(double), n, fp);

    fclose(fp);

    return (written == n) ? 0 : -1;
}

/*
 * Write a small human-readable summary.
 */
int write_summary(const char *filename,
                  size_t nx,
                  size_t ny,
                  size_t steps,
                  double checksum)
{
    FILE *fp = fopen(filename, "w");

    if (fp == NULL) {
        return -1;
    }

    fprintf(fp, "nx=%zu\n", nx);
    fprintf(fp, "ny=%zu\n", ny);
    fprintf(fp, "steps=%zu\n", steps);
    fprintf(fp, "checksum=%.17g\n", checksum);

    fclose(fp);
    return 0;
}
