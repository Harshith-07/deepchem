"""
Contains an abstract base class that supports different ML models.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
import sys
import numpy as np
import pandas as pd
import joblib
import os
from deepchem.datasets import Dataset
from deepchem.utils.save import load_from_disk
from deepchem.utils.save import save_to_disk
from deepchem.utils.save import log

def undo_transforms(y, transformers):
  """Undoes all transformations applied."""
  # Note that transformers have to be undone in reversed order
  for transformer in reversed(transformers):
    y = transformer.untransform(y)
  return y

class Model(object):
  """
  Abstract base class for different ML models.
  """
  non_sklearn_models = ["SingleTaskDNN", "MultiTaskDNN", "DockingDNN"]
  def __init__(self, task_types, model_params, fit_transformers=None,
               model_instance=None, initialize_raw_model=True, 
               verbosity=None, **kwargs):
    self.model_class = model_instance.__class__
    self.task_types = task_types
    self.model_params = model_params
    self.fit_transformers = fit_transformers
    self.raw_model = None
    assert verbosity in [None, "low", "high"]
    self.verbosity = verbosity

  def fit_on_batch(self, X, y, w):
    """
    Updates existing model with new information.
    """
    raise NotImplementedError(
        "Each model is responsible for its own fit_on_batch method.")

  def predict_on_batch(self, X):
    """
    Makes predictions on given batch of new data.
    """
    raise NotImplementedError(
        "Each model is responsible for its own predict_on_batch method.")

  def set_raw_model(self, raw_model):
    """
    Set underlying raw model. Useful when loading from disk.
    """
    self.raw_model = raw_model

  def get_raw_model(self):
    """
    Return raw model.
    """
    return self.raw_model

  @staticmethod
  def get_model_filename(out_dir):
    """
    Given model directory, obtain filename for the model itself.
    """
    return os.path.join(out_dir, "model.joblib")

  @staticmethod
  def get_params_filename(out_dir):
    """
    Given model directory, obtain filename for the model itself.
    """
    return os.path.join(out_dir, "model_params.joblib")

  def save(self, out_dir):
    """Dispatcher function for saving."""
    params = {"model_params" : self.model_params,
              "task_types" : self.task_types,
              "model_class": self.__class__}
    save_to_disk(params, Model.get_params_filename(out_dir))

  def fit(self, dataset):
    """
    Fits a model on data in a Dataset object.
    """
    # TODO(rbharath/enf): We need a structured way to deal with potential GPU
    #                     memory overflows.
    batch_size = self.model_params["batch_size"]
    for epoch in range(self.model_params["nb_epoch"]):
      log("Starting epoch %s" % str(epoch+1), self.verbosity)
      for (X_batch, y_batch, w_batch, _) in dataset.iterbatches(batch_size):
        if self.fit_transformers:
          X_batch, y_batch, w_batch = self.transform_on_batch(X_batch, y_batch, w_batch)
        self.fit_on_batch(X_batch, y_batch, w_batch)

  def transform_on_batch(self, X, y, w):
    """
    Transforms data in a Dataset object with Transformer objects.
    """
    # Create dataset 
    for transformer in self.fit_transformers:
      transformer.transform(batch_dataset)

  # TODO(rbharath): The structure of the produced df might be
  # complicated. Better way to model?
  def predict(self, dataset, transformers):
    """
    Uses self to make predictions on provided Dataset object.
    """
    task_names = dataset.get_task_names()
    pred_task_names = ["%s_pred" % task_name for task_name in task_names]
    w_task_names = ["%s_weight" % task_name for task_name in task_names]
    raw_task_names = [task_name+"_raw" for task_name in task_names]
    raw_pred_task_names = [pred_task_name+"_raw" for pred_task_name in pred_task_names]
    column_names = (['ids'] + raw_task_names + task_names
                    + raw_pred_task_names + pred_task_names + w_task_names
                    + ["y_means", "y_stds"])
    pred_y_df = pd.DataFrame(columns=column_names)

    batch_size = self.model_params["batch_size"]
    for (X_batch, y_batch, w_batch, ids_batch) in dataset.iterbatches(batch_size):
      y_pred = self.predict_on_batch(X_batch)
      y_pred = np.reshape(y_pred, np.shape(y_batch))

      # Now undo transformations on y, y_pred
      y_raw, y_pred_raw = y_batch, y_pred
      y_batch = undo_transforms(y_batch, transformers)
      y_pred = undo_transforms(y_pred, transformers)

      batch_df = pd.DataFrame(columns=column_names)
      batch_df['ids'] = ids_batch
      batch_df[raw_task_names] = y_raw
      batch_df[task_names] = y_batch
      batch_df[raw_pred_task_names] = y_pred_raw
      batch_df[pred_task_names] = y_pred
      batch_df[w_task_names] = w_batch
      pred_y_df = pd.concat([pred_y_df, batch_df])

    return pred_y_df

  def get_task_type(self):
    """
    Currently models can only be classifiers or regressors.
    """
    # TODO(rbharath): This is a hack based on fact that multi-tasktype models
    # aren't supported.
    return self.task_types.itervalues().next()
