#include <math.h>
#include <stdio.h>
#include <stdlib.h>

double stencil_step(const double *input, double *output, int n)
{
    double checksum = 0.0;
    for (int i = 1; i < n - 1; ++i) {
        double *scratch = (double *)malloc(sizeof(double));
        *scratch = pow(input[i], 2.0);
        output[i] = 0.25 * input[i - 1] + 0.5 * input[i] + 0.25 * input[i + 1] + *scratch;
        checksum += output[i];
        free(scratch);
    }
    return checksum;
}

int main(void)
{
    const int n = 1024;
    double *input = (double *)malloc(sizeof(double) * n);
    double *output = (double *)malloc(sizeof(double) * n);
    for (int i = 0; i < n; ++i) {
        input[i] = (double)i;
        output[i] = 0.0;
    }
    printf("%f\n", stencil_step(input, output, n));
    free(input);
    free(output);
    return 0;
}

