#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  int level;
  int atomnum;
  int spin_p_switch;
  int spin_dim;
  int Catomnum;
  int Latomnum;
  int Ratomnum;
  int TCpyCell;
  int order_max;
  int nao_max;
  int num_edges;
  int *nao_per_atom;
  int *fnan;
  int *natn_flat;
  int *ncn_flat;
  double *atv;
  int *atv_ijk;
  double *tv;
  double *rtv;
  double *pos;
  int *cell_shift;
  double *nbr_shift;
  int *edge_index;
  int *inv_edge_idx;
  double *Son;
  double *Soff;
  double *Hon;
  double *Hoff;
  double *dSon;
  double *dSoff;
} PostprocessScfout;

static char g_last_error[1024];

static void set_error(const char *fmt, ...)
{
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(g_last_error, sizeof(g_last_error), fmt, ap);
  va_end(ap);
}

const char *postprocess_scfout_last_error(void)
{
  return g_last_error;
}

static int read_ints(FILE *fp, int *dst, size_t count)
{
  return fread(dst, sizeof(int), count, fp) == count;
}

static int read_doubles(FILE *fp, double *dst, size_t count)
{
  return fread(dst, sizeof(double), count, fp) == count;
}

static void *xcalloc(size_t n, size_t size)
{
  void *ptr = calloc(n, size);
  if (ptr == NULL) {
    set_error("allocation failed");
  }
  return ptr;
}

static void free_postprocess_scfout_partial(PostprocessScfout *data)
{
  if (data == NULL) return;
  free(data->nao_per_atom);
  free(data->fnan);
  free(data->natn_flat);
  free(data->ncn_flat);
  free(data->atv);
  free(data->atv_ijk);
  free(data->tv);
  free(data->rtv);
  free(data->pos);
  free(data->cell_shift);
  free(data->nbr_shift);
  free(data->edge_index);
  free(data->inv_edge_idx);
  free(data->Son);
  free(data->Soff);
  free(data->Hon);
  free(data->Hoff);
  free(data->dSon);
  free(data->dSoff);
  free(data);
}

void free_postprocess_scfout(PostprocessScfout *data)
{
  free_postprocess_scfout_partial(data);
}

static void copy_block(double *dst, int nao_max2, const double *src, int count)
{
  memcpy(dst, src, sizeof(double) * count);
  if (count < nao_max2) {
    memset(dst + count, 0, sizeof(double) * (nao_max2 - count));
  }
}

static int pair_value_count(int atomnum, const int *fnan, const int *nao, const int *natn_flat)
{
  int total = 0;
  int offset = 0;
  int ct_an, h_an;
  for (ct_an = 0; ct_an < atomnum; ct_an++) {
    int tno1 = nao[ct_an];
    for (h_an = 0; h_an <= fnan[ct_an]; h_an++) {
      int gh_an = natn_flat[offset + h_an] - 1;
      int tno2 = nao[gh_an];
      total += tno1 * tno2;
    }
    offset += fnan[ct_an] + 1;
  }
  return total;
}

static int build_inverse_edges(PostprocessScfout *data, const int *edge_shift)
{
  int edge_idx, other_idx;
  for (edge_idx = 0; edge_idx < data->num_edges; edge_idx++) {
    int src = data->edge_index[edge_idx];
    int dst = data->edge_index[data->num_edges + edge_idx];
    int sx = edge_shift[3 * edge_idx + 0];
    int sy = edge_shift[3 * edge_idx + 1];
    int sz = edge_shift[3 * edge_idx + 2];
    int found = -1;
    for (other_idx = 0; other_idx < data->num_edges; other_idx++) {
      int osrc = data->edge_index[other_idx];
      int odst = data->edge_index[data->num_edges + other_idx];
      int ox = edge_shift[3 * other_idx + 0];
      int oy = edge_shift[3 * other_idx + 1];
      int oz = edge_shift[3 * other_idx + 2];
      if (osrc == dst && odst == src && ox + sx == 0 && oy + sy == 0 && oz + sz == 0) {
        found = other_idx;
        break;
      }
    }
    if (found < 0) {
      set_error("failed to find inverse edge for edge %d", edge_idx);
      return 0;
    }
    data->inv_edge_idx[edge_idx] = found;
  }
  return 1;
}

PostprocessScfout *parse_postprocess_scfout(const char *path)
{
  FILE *fp = NULL;
  PostprocessScfout *data = NULL;
  int header[6];
  int encoded;
  int total_neigh = 0;
  int nao_max2;
  int *row_offsets = NULL;
  double *tmp = NULL;
  int need_h0, need_ds;
  int pair_sum;
  int edge_idx;
  int ct_an, h_an, spin, dir;
  int *edge_shift = NULL;

  g_last_error[0] = '\0';
  fp = fopen(path, "rb");
  if (fp == NULL) {
    set_error("failed to open %s: %s", path, strerror(errno));
    return NULL;
  }

  if (!read_ints(fp, header, 6)) {
    set_error("failed to read header");
    fclose(fp);
    return NULL;
  }

  encoded = header[1];
  data = (PostprocessScfout *)xcalloc(1, sizeof(PostprocessScfout));
  if (data == NULL) {
    fclose(fp);
    return NULL;
  }

  data->atomnum = header[0];
  data->spin_p_switch = encoded % 4;
  data->spin_dim = data->spin_p_switch + 1;
  data->level = encoded / 4;
  data->Catomnum = header[2];
  data->Latomnum = header[3];
  data->Ratomnum = header[4];
  data->TCpyCell = header[5];

  if (data->atomnum <= 0) {
    set_error("invalid atomnum %d", data->atomnum);
    goto fail;
  }
  if (data->level < 1 || data->level > 4) {
    set_error("invalid postprocess level %d", data->level);
    goto fail;
  }

  if (!read_ints(fp, &data->order_max, 1)) {
    set_error("failed to read order_max");
    goto fail;
  }

  data->atv = (double *)xcalloc((size_t)(data->TCpyCell + 1) * 4, sizeof(double));
  data->atv_ijk = (int *)xcalloc((size_t)(data->TCpyCell + 1) * 4, sizeof(int));
  data->nao_per_atom = (int *)xcalloc((size_t)data->atomnum, sizeof(int));
  data->fnan = (int *)xcalloc((size_t)data->atomnum, sizeof(int));
  data->tv = (double *)xcalloc(12, sizeof(double));
  data->rtv = (double *)xcalloc(12, sizeof(double));
  data->pos = (double *)xcalloc((size_t)data->atomnum * 3, sizeof(double));
  if (!data->atv || !data->atv_ijk || !data->nao_per_atom || !data->fnan || !data->tv || !data->rtv || !data->pos) {
    goto fail;
  }

  if (!read_doubles(fp, data->atv, (size_t)(data->TCpyCell + 1) * 4)) {
    set_error("failed to read atv");
    goto fail;
  }
  if (!read_ints(fp, data->atv_ijk, (size_t)(data->TCpyCell + 1) * 4)) {
    set_error("failed to read atv_ijk");
    goto fail;
  }
  if (!read_ints(fp, data->nao_per_atom, (size_t)data->atomnum)) {
    set_error("failed to read nao_per_atom");
    goto fail;
  }
  if (!read_ints(fp, data->fnan, (size_t)data->atomnum)) {
    set_error("failed to read fnan");
    goto fail;
  }

  for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
    total_neigh += data->fnan[ct_an] + 1;
    if (data->nao_per_atom[ct_an] > data->nao_max) {
      data->nao_max = data->nao_per_atom[ct_an];
    }
  }
  nao_max2 = data->nao_max * data->nao_max;
  data->natn_flat = (int *)xcalloc((size_t)total_neigh, sizeof(int));
  data->ncn_flat = (int *)xcalloc((size_t)total_neigh, sizeof(int));
  row_offsets = (int *)xcalloc((size_t)(data->atomnum + 1), sizeof(int));
  if (!data->natn_flat || !data->ncn_flat || !row_offsets) {
    goto fail;
  }

  row_offsets[0] = 0;
  for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
    row_offsets[ct_an + 1] = row_offsets[ct_an] + data->fnan[ct_an] + 1;
  }

  if (!read_ints(fp, data->natn_flat, (size_t)total_neigh)) {
    set_error("failed to read natn");
    goto fail;
  }
  if (!read_ints(fp, data->ncn_flat, (size_t)total_neigh)) {
    set_error("failed to read ncn");
    goto fail;
  }
  if (!read_doubles(fp, data->tv, 12)) {
    set_error("failed to read tv");
    goto fail;
  }
  if (!read_doubles(fp, data->rtv, 12)) {
    set_error("failed to read rtv");
    goto fail;
  }

  tmp = (double *)xcalloc((size_t)data->atomnum * 4, sizeof(double));
  if (tmp == NULL) goto fail;
  if (!read_doubles(fp, tmp, (size_t)data->atomnum * 4)) {
    set_error("failed to read Gxyz");
    goto fail;
  }
  for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
    data->pos[3 * ct_an + 0] = tmp[4 * ct_an + 1];
    data->pos[3 * ct_an + 1] = tmp[4 * ct_an + 2];
    data->pos[3 * ct_an + 2] = tmp[4 * ct_an + 3];
  }
  free(tmp);
  tmp = NULL;

  data->num_edges = 0;
  for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
    data->num_edges += data->fnan[ct_an];
  }
  data->edge_index = (int *)xcalloc((size_t)data->num_edges * 2, sizeof(int));
  data->inv_edge_idx = (int *)xcalloc((size_t)data->num_edges, sizeof(int));
  data->cell_shift = (int *)xcalloc((size_t)data->num_edges * 3, sizeof(int));
  data->nbr_shift = (double *)xcalloc((size_t)data->num_edges * 3, sizeof(double));
  edge_shift = (int *)xcalloc((size_t)data->num_edges * 3, sizeof(int));
  if (!data->edge_index || !data->inv_edge_idx || !data->cell_shift || !data->nbr_shift || !edge_shift) goto fail;

  edge_idx = 0;
  for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
    int offset = row_offsets[ct_an];
    for (h_an = 1; h_an <= data->fnan[ct_an]; h_an++) {
      int rn = data->ncn_flat[offset + h_an];
      data->edge_index[edge_idx] = ct_an;
      data->edge_index[data->num_edges + edge_idx] = data->natn_flat[offset + h_an] - 1;
      edge_shift[3 * edge_idx + 0] = data->atv_ijk[4 * rn + 1];
      edge_shift[3 * edge_idx + 1] = data->atv_ijk[4 * rn + 2];
      edge_shift[3 * edge_idx + 2] = data->atv_ijk[4 * rn + 3];
      data->cell_shift[3 * edge_idx + 0] = edge_shift[3 * edge_idx + 0];
      data->cell_shift[3 * edge_idx + 1] = edge_shift[3 * edge_idx + 1];
      data->cell_shift[3 * edge_idx + 2] = edge_shift[3 * edge_idx + 2];
      data->nbr_shift[3 * edge_idx + 0] = data->atv[4 * rn + 1];
      data->nbr_shift[3 * edge_idx + 1] = data->atv[4 * rn + 2];
      data->nbr_shift[3 * edge_idx + 2] = data->atv[4 * rn + 3];
      edge_idx++;
    }
  }
  if (!build_inverse_edges(data, edge_shift)) goto fail;

  need_h0 = (data->level == 3 || data->level == 4);
  need_ds = (data->level == 2 || data->level == 4);
  pair_sum = pair_value_count(data->atomnum, data->fnan, data->nao_per_atom, data->natn_flat);

  data->Son = (double *)xcalloc((size_t)data->atomnum * nao_max2, sizeof(double));
  data->Soff = (double *)xcalloc((size_t)data->num_edges * nao_max2, sizeof(double));
  if (!data->Son || !data->Soff) goto fail;
  if (need_h0) {
    data->Hon = (double *)xcalloc((size_t)data->spin_dim * data->atomnum * nao_max2, sizeof(double));
    data->Hoff = (double *)xcalloc((size_t)data->spin_dim * data->num_edges * nao_max2, sizeof(double));
    if (!data->Hon || !data->Hoff) goto fail;
  }
  if (need_ds) {
    data->dSon = (double *)xcalloc((size_t)3 * data->atomnum * nao_max2, sizeof(double));
    data->dSoff = (double *)xcalloc((size_t)3 * data->num_edges * nao_max2, sizeof(double));
    if (!data->dSon || !data->dSoff) {
      goto fail;
    }
  }

  tmp = (double *)xcalloc((size_t)nao_max2, sizeof(double));
  if (tmp == NULL) goto fail;

  if (need_h0) {
    for (spin = 0; spin < data->spin_dim; spin++) {
      edge_idx = 0;
      for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
        int offset = row_offsets[ct_an];
        int tno1 = data->nao_per_atom[ct_an];
        for (h_an = 0; h_an <= data->fnan[ct_an]; h_an++) {
          int gh_an = data->natn_flat[offset + h_an] - 1;
          int tno2 = data->nao_per_atom[gh_an];
          int count = tno1 * tno2;
          if (!read_doubles(fp, tmp, (size_t)count)) {
            set_error("failed to read H block");
            goto fail;
          }
          if (h_an == 0) {
            copy_block(data->Hon + (size_t)spin * data->atomnum * nao_max2 + (size_t)ct_an * nao_max2, nao_max2, tmp, count);
          }
          else {
            copy_block(data->Hoff + (size_t)spin * data->num_edges * nao_max2 + (size_t)edge_idx * nao_max2, nao_max2, tmp, count);
            edge_idx++;
          }
        }
      }
    }

    if (data->spin_p_switch == 3) {
      for (spin = 0; spin < 3; spin++) {
        for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
          int offset = row_offsets[ct_an];
          int tno1 = data->nao_per_atom[ct_an];
          for (h_an = 0; h_an <= data->fnan[ct_an]; h_an++) {
            int gh_an = data->natn_flat[offset + h_an] - 1;
            int tno2 = data->nao_per_atom[gh_an];
            int count = tno1 * tno2;
            if (!read_doubles(fp, tmp, (size_t)count)) {
              set_error("failed to skip noncollinear auxiliary block");
              goto fail;
            }
          }
        }
      }
    }
  }

  edge_idx = 0;
  for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
    int offset = row_offsets[ct_an];
    int tno1 = data->nao_per_atom[ct_an];
    for (h_an = 0; h_an <= data->fnan[ct_an]; h_an++) {
      int gh_an = data->natn_flat[offset + h_an] - 1;
      int tno2 = data->nao_per_atom[gh_an];
      int count = tno1 * tno2;
      if (!read_doubles(fp, tmp, (size_t)count)) {
        set_error("failed to read S block");
        goto fail;
      }
      if (h_an == 0) {
        copy_block(data->Son + (size_t)ct_an * nao_max2, nao_max2, tmp, count);
      }
      else {
        copy_block(data->Soff + (size_t)edge_idx * nao_max2, nao_max2, tmp, count);
        edge_idx++;
      }
    }
  }

  if (need_ds) {
    for (dir = 0; dir < 3; dir++) {
      edge_idx = 0;
      for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
        int offset = row_offsets[ct_an];
        int tno1 = data->nao_per_atom[ct_an];
        for (h_an = 0; h_an <= data->fnan[ct_an]; h_an++) {
          int gh_an = data->natn_flat[offset + h_an] - 1;
          int tno2 = data->nao_per_atom[gh_an];
          int count = tno1 * tno2;
          if (!read_doubles(fp, tmp, (size_t)count)) {
            set_error("failed to read dS block");
            goto fail;
          }
          if (h_an == 0) {
            copy_block(data->dSon + ((size_t)dir * data->atomnum + ct_an) * nao_max2, nao_max2, tmp, count);
          }
          else {
            copy_block(data->dSoff + ((size_t)dir * data->num_edges + edge_idx) * nao_max2, nao_max2, tmp, count);
            edge_idx++;
          }
        }
      }
    }
  }

  free(tmp);
  free(edge_shift);
  free(row_offsets);
  fclose(fp);
  if (pair_sum < 0) {
    set_error("invalid pair count");
    goto fail_after_close;
  }
  return data;

fail:
  if (tmp != NULL) free(tmp);
  if (edge_shift != NULL) free(edge_shift);
  if (row_offsets != NULL) free(row_offsets);
  if (fp != NULL) fclose(fp);
fail_after_close:
  free_postprocess_scfout_partial(data);
  return NULL;
}
