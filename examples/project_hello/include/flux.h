/* flux.h — Roe-scheme flux kernel interface */
#ifndef FLUX_H
#define FLUX_H

void roe_flux(const double *hL, const double *hR,
              const double *uL, const double *uR,
              double *flux_h, double *flux_u,
              int n, double g);

void compute_bed_slope(const double *z, const double *h,
                       double *Sb, int n, double dx);

double max_wave_speed(const double *h, const double *u,
                      int n, double g);

#endif
