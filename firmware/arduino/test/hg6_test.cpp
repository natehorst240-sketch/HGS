// Host-side gate for the C++ .HG6 decoder: prints the decoded file in a fixed
// line format; the Makefile diffs it against hg6_expected.py (the Python
// parser, which was verified value-for-value against the Windows app).
#include "../hgs_stick/hg6.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char** argv) {
  if (argc < 2) { fprintf(stderr, "usage: hg6_test FILE.HG6\n"); return 2; }
  FILE* f = fopen(argv[1], "rb");
  if (!f) { perror(argv[1]); return 2; }
  fseek(f, 0, SEEK_END);
  const long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  uint8_t* buf = (uint8_t*)malloc(n > 0 ? n : 1);
  if (fread(buf, 1, n, f) != (size_t)n) { perror("read"); return 2; }
  fclose(f);

  static hg6::Parsed p;
  hg6::parse(buf, (size_t)n, p);

  printf("params %d\n", p.params);
  for (int i = 0; i < p.ncum; ++i) printf("cum|%s|%s\n", p.cum[i].item, p.cum[i].value);
  for (int i = 0; i < p.nev; ++i)
    if (!p.ev[i].afcs) printf("fault|%s|%s|%s|%d\n", p.ev[i].label, p.ev[i].first, p.ev[i].last, p.ev[i].count);
  for (int i = 0; i < p.nev; ++i)
    if (p.ev[i].afcs) printf("afcs|%s|%s|%s|%d\n", p.ev[i].label, p.ev[i].first, p.ev[i].last, p.ev[i].count);
  for (int i = 0; i < p.npa; ++i) {
    printf("pa");
    for (int c = 0; c < hg6::PA_COLS; ++c) printf("|%s", p.pa[i].col[c]);
    printf("\n");
  }
  printf("th frames=%d samples=%d first=%s last=%s\n", p.th.frames, p.th.samples, p.th.first, p.th.last);
  free(buf);
  return 0;
}
