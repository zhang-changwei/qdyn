#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <numpy/arrayobject.h>

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

extern PostprocessScfout *parse_postprocess_scfout(const char *path);
extern void free_postprocess_scfout(PostprocessScfout *data);
extern const char *postprocess_scfout_last_error(void);

static void capsule_destructor(PyObject *capsule)
{
  PostprocessScfout *data = (PostprocessScfout *)PyCapsule_GetPointer(capsule, "PostprocessScfout");
  if (data != NULL) {
    free_postprocess_scfout(data);
  }
}

static PyObject *array_from_data(void *ptr, int typenum, int nd, npy_intp *dims, PyObject *capsule)
{
  PyObject *array = PyArray_SimpleNewFromData(nd, dims, typenum, ptr);
  if (array == NULL) {
    return NULL;
  }
  Py_INCREF(capsule);
  if (PyArray_SetBaseObject((PyArrayObject *)array, capsule) < 0) {
    Py_DECREF(capsule);
    Py_DECREF(array);
    return NULL;
  }
  return array;
}

static PyObject *build_nested_int_lists(const int *flat, const int *fnan, int atomnum)
{
  PyObject *outer = PyList_New(atomnum);
  int offset = 0;
  int ct_an;
  if (outer == NULL) return NULL;
  for (ct_an = 0; ct_an < atomnum; ct_an++) {
    int width = fnan[ct_an] + 1;
    PyObject *inner = PyList_New(width);
    int i;
    if (inner == NULL) {
      Py_DECREF(outer);
      return NULL;
    }
    for (i = 0; i < width; i++) {
      PyObject *value = PyLong_FromLong(flat[offset + i]);
      if (value == NULL) {
        Py_DECREF(inner);
        Py_DECREF(outer);
        return NULL;
      }
      PyList_SET_ITEM(inner, i, value);
    }
    offset += width;
    PyList_SET_ITEM(outer, ct_an, inner);
  }
  return outer;
}

static int dict_set_steal(PyObject *dict, const char *key, PyObject *value)
{
  int rc;
  if (value == NULL) return -1;
  rc = PyDict_SetItemString(dict, key, value);
  Py_DECREF(value);
  return rc;
}

static PyObject *py_read_scfout(PyObject *self, PyObject *args)
{
  const char *path;
  PostprocessScfout *data;
  PyObject *capsule = NULL;
  PyObject *result = NULL;
  npy_intp dims1[1], dims2[2], dims3[3];
  int total_neigh = 0;
  int ct_an;

  (void)self;

  if (!PyArg_ParseTuple(args, "s", &path)) {
    return NULL;
  }

  data = parse_postprocess_scfout(path);
  if (data == NULL) {
    PyErr_SetString(PyExc_RuntimeError, postprocess_scfout_last_error());
    return NULL;
  }

  for (ct_an = 0; ct_an < data->atomnum; ct_an++) {
    total_neigh += data->fnan[ct_an] + 1;
  }

  capsule = PyCapsule_New((void *)data, "PostprocessScfout", capsule_destructor);
  if (capsule == NULL) {
    free_postprocess_scfout(data);
    return NULL;
  }

  result = PyDict_New();
  if (result == NULL) {
    Py_DECREF(capsule);
    return NULL;
  }

  if (PyDict_SetItemString(result, "level", PyLong_FromLong(data->level)) < 0) goto fail;
  if (PyDict_SetItemString(result, "atomnum", PyLong_FromLong(data->atomnum)) < 0) goto fail;
  if (PyDict_SetItemString(result, "spin_p_switch", PyLong_FromLong(data->spin_p_switch)) < 0) goto fail;
  if (PyDict_SetItemString(result, "spin_dim", PyLong_FromLong(data->spin_dim)) < 0) goto fail;
  if (PyDict_SetItemString(result, "Catomnum", PyLong_FromLong(data->Catomnum)) < 0) goto fail;
  if (PyDict_SetItemString(result, "Latomnum", PyLong_FromLong(data->Latomnum)) < 0) goto fail;
  if (PyDict_SetItemString(result, "Ratomnum", PyLong_FromLong(data->Ratomnum)) < 0) goto fail;
  if (PyDict_SetItemString(result, "TCpyCell", PyLong_FromLong(data->TCpyCell)) < 0) goto fail;
  if (PyDict_SetItemString(result, "order_max", PyLong_FromLong(data->order_max)) < 0) goto fail;
  if (PyDict_SetItemString(result, "nao_max", PyLong_FromLong(data->nao_max)) < 0) goto fail;
  if (PyDict_SetItemString(result, "num_edges", PyLong_FromLong(data->num_edges)) < 0) goto fail;

  dims1[0] = data->atomnum;
  if (dict_set_steal(result, "nao_per_atom", array_from_data(data->nao_per_atom, NPY_INT32, 1, dims1, capsule)) < 0) goto fail;
  if (dict_set_steal(result, "fnan", array_from_data(data->fnan, NPY_INT32, 1, dims1, capsule)) < 0) goto fail;

  if (dict_set_steal(result, "natn", build_nested_int_lists(data->natn_flat, data->fnan, data->atomnum)) < 0) goto fail;
  if (dict_set_steal(result, "ncn", build_nested_int_lists(data->ncn_flat, data->fnan, data->atomnum)) < 0) goto fail;

  dims2[0] = data->TCpyCell + 1;
  dims2[1] = 4;
  if (dict_set_steal(result, "atv", array_from_data(data->atv, NPY_FLOAT64, 2, dims2, capsule)) < 0) goto fail;
  if (dict_set_steal(result, "atv_ijk", array_from_data(data->atv_ijk, NPY_INT32, 2, dims2, capsule)) < 0) goto fail;

  dims2[0] = 3;
  dims2[1] = 4;
  if (dict_set_steal(result, "tv", array_from_data(data->tv, NPY_FLOAT64, 2, dims2, capsule)) < 0) goto fail;
  if (dict_set_steal(result, "rtv", array_from_data(data->rtv, NPY_FLOAT64, 2, dims2, capsule)) < 0) goto fail;

  dims2[0] = data->atomnum;
  dims2[1] = 3;
  if (dict_set_steal(result, "pos", array_from_data(data->pos, NPY_FLOAT64, 2, dims2, capsule)) < 0) goto fail;
  dims2[0] = data->num_edges;
  dims2[1] = 3;
  if (dict_set_steal(result, "cell_shift", array_from_data(data->cell_shift, NPY_INT32, 2, dims2, capsule)) < 0) goto fail;
  if (dict_set_steal(result, "nbr_shift", array_from_data(data->nbr_shift, NPY_FLOAT64, 2, dims2, capsule)) < 0) goto fail;

  dims2[0] = 2;
  dims2[1] = data->num_edges;
  if (dict_set_steal(result, "edge_index", array_from_data(data->edge_index, NPY_INT32, 2, dims2, capsule)) < 0) goto fail;
  dims1[0] = data->num_edges;
  if (dict_set_steal(result, "inv_edge_idx", array_from_data(data->inv_edge_idx, NPY_INT32, 1, dims1, capsule)) < 0) goto fail;

  dims2[0] = data->atomnum;
  dims2[1] = data->nao_max * data->nao_max;
  if (dict_set_steal(result, "Son", array_from_data(data->Son, NPY_FLOAT64, 2, dims2, capsule)) < 0) goto fail;
  dims2[0] = data->num_edges;
  if (dict_set_steal(result, "Soff", array_from_data(data->Soff, NPY_FLOAT64, 2, dims2, capsule)) < 0) goto fail;

  dims3[0] = data->spin_dim;
  dims3[1] = data->atomnum;
  dims3[2] = data->nao_max * data->nao_max;
  if (data->Hon != NULL) {
    if (dict_set_steal(result, "Hon", array_from_data(data->Hon, NPY_FLOAT64, 3, dims3, capsule)) < 0) goto fail;
  }
  dims3[1] = data->num_edges;
  if (data->Hoff != NULL) {
    if (dict_set_steal(result, "Hoff", array_from_data(data->Hoff, NPY_FLOAT64, 3, dims3, capsule)) < 0) goto fail;
  }

  dims3[0] = 3;
  dims3[1] = data->atomnum;
  dims3[2] = data->nao_max * data->nao_max;
  if (data->dSon != NULL) {
    if (dict_set_steal(result, "dSon", array_from_data(data->dSon, NPY_FLOAT64, 3, dims3, capsule)) < 0) goto fail;
  }
  dims3[1] = data->num_edges;
  if (data->dSoff != NULL) {
    if (dict_set_steal(result, "dSoff", array_from_data(data->dSoff, NPY_FLOAT64, 3, dims3, capsule)) < 0) goto fail;
  }

  Py_DECREF(capsule);
  return result;

fail:
  Py_DECREF(result);
  Py_DECREF(capsule);
  return NULL;
}

static PyMethodDef module_methods[] = {
    {"read_scfout", py_read_scfout, METH_VARARGS, "Read postprocess scfout and return a Python dict."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_read_openmx_postprocess_ext",
    NULL,
    -1,
    module_methods,
};

PyMODINIT_FUNC PyInit__read_openmx_postprocess_ext(void)
{
  PyObject *module;
  import_array();
  module = PyModule_Create(&moduledef);
  return module;
}
