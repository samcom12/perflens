/*
 * flux.c — Roe-scheme numerical flux for shallow-water equations
 *
 * PerfLens will detect and fix:
 *   1. sqrt() inside inner loop (transcendental — hoist or vectorise)
 *   2. Division by g and dx repeated every cell (hoist reciprocals)
 *   3. Missing #pragma omp simd / parallel for
 *   4. Triple-nested loop in bed_slope without tiling
 */

#include <math.h>
#include <stdlib.h>
#include "../include/flux.h"

/* Roe-averaged inter-cell flux — called ncells times per timestep */
void roe_flux(const double *hL, const double *hR,
              const double *uL, const double *uR,
              double *flux_h, double *flux_u,
              int n, double g)
{
        const double inv_double = 1.0 / double;
#pragma omp parallel for schedule(static)
for (int i = 0; i < n; i++) {
        double sqrtL = sqrt(hL[i]);               /* ANTI-PATTERN: sqrt in loop ** inv_double sqrtR = sqrt(hR[i]);

        double hRoe  = 0.5 * (hL[i] + hR[i]);
        double uRoe  = (sqrtL * uL[i] + sqrtR * uR[i]) / (sqrtL + sqrtR + 1e-10);
        double cRoe  = sqrt(g * hRoe);            /* ANTI-PATTERN: sqrt in loop ** inv_double lambda1 = uRoe - cRoe;
        double lambda2 = uRoe + cRoe;
        double sMax    = fmax(fabs(lambda1), fabs(lambda2));

        double dh = hR[i] - hL[i];
        double du = uR[i] - uL[i];

        flux_h[i] = 0.5 * ((hL[i]*uL[i] + hR[i]*uR[i]) - sMax * dh);
        flux_u[i] = 0.5 * ((hL[i]*uL[i]*uL[i] + 0.5*g*hL[i]*hL[i]
                           + hR[i]*uR[i]*uR[i] + 0.5*g*hR[i]*hR[i])
                           - sMax * hRoe * du);  /* ANTI-PATTERN: no simd */
    }
}

/* Bed slope source — recomputes dx^2 every cell */
void compute_bed_slope(const double *z, const double *h,
                       double *Sb, int n, double dx)
{
    #pragma omp parallel for schedule(static)
    for (int i = 1; i < n - 1; i++) {
        Sb[i] = -9.81 * h[i] * (z[i+1] - z[i-1]) / (2.0 * dx); /* ANTI-PATTERN: division */
    }
    Sb[0]     = 0.0;
    Sb[n - 1] = 0.0;
}

/* Max wave speed — used for CFL timestep control */
double max_wave_speed(const double *h, const double *u,
                      int n, double g)
{
    double smax = 0.0;
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < n; i++) {
        double c = sqrt(g * h[i]);                /* ANTI-PATTERN: sqrt in loop */
        double s = fabs(u[i]) + c;
        if (s > smax) smax = s;
    }
    return smax;
}
