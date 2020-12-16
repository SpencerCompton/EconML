# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
# This code contains snippets of code from:
# https://github.com/scikit-learn/scikit-learn/blob/master/sklearn/tree/_classes.py

import numpy as np
import numbers
from math import ceil
from ..tree import Tree
from ._criterion import LinearMomentGRFCriterionMSE, LinearMomentGRFCriterion
from ..tree._criterion import Criterion
from ..tree._splitter import Splitter, BestSplitter
from ..tree import DepthFirstTreeBuilder
from . import _criterion
from ..tree import _tree
from sklearn.base import BaseEstimator
from sklearn.model_selection import train_test_split
from sklearn.utils import check_array
from sklearn.utils import check_random_state
from sklearn.utils.validation import _check_sample_weight
from sklearn.utils.validation import check_is_fitted
import copy

# =============================================================================
# Types and constants
# =============================================================================

DTYPE = _tree.DTYPE
DOUBLE = _tree.DOUBLE

CRITERIA_GRF = {"het": LinearMomentGRFCriterion,
                "mse": LinearMomentGRFCriterionMSE}

SPLITTERS = {"best": BestSplitter, }

MAX_INT = np.iinfo(np.int32).max

# =============================================================================
# Base GRF tree
# =============================================================================


class GRFTree(BaseEstimator):
    """A tree of a Generalized Random Forest. This method should be used primarily
    through the BaseGRF forest class and its derivatives and not as a standalone
    estimator.

    Parameters
    ----------
    criterion : {"mse", "het"}, default="mse"
        The function to measure the quality of a split. Supported criteria
        are "mse" for the mean squared error in a linear moment estimation
        tree and "het" for heterogeneity score. For any linear moment problem
        of the form:

            E[J * theta(x) - A | X = x] = 0

        - The "mse" criterion finds splits that maximize the score:

            sum_{child in {left, right}} weight(child) * theta(child).T @ E[J | X in child] @ theta(child)

            - In the case of a causal tree, this coincides with minimizing the MSE:
              sum_{child in {left, right}} E[(Y - <theta(child), T>)^2 | X=child] weight(child)
            - In the case of an IV tree, this roughly coincides with minimize the projected MSE:
              sum_{child in {left, right}} E[(Y - <theta(child), E[T|Z]>)^2 | X=child] weight(child)
          Internally, for the case of more than two treatments or for the case of one treatment with
          `fit_intercept=True` then this criterion is approximated by computationally simpler variants for
          computationaly purposes. In particular, it is replaced by:
              sum_{child in {left, right}} weight(child) * rho(child).T @ E[J | X in child] @ rho(child)
          where:
              rho(child) := J(parent)^{-1} E[A - J * theta(parent) | X in child]
          This can be thought as a heterogeneity inducing score, but putting more weight on scores
          with a large minimum eigenvalue of the child jacobian E[J | X in child], which leads to smaller
          variance of the estimate and stronger identification of the parameters.

        - The "het" criterion finds splits that maximize the pure parameter heterogeneity score:
              sum_{child in {left, right}} weight(child) * rho(child).T @ rho(child)
          This can be thought as an approximation to the ideal heterogeneity score:
              weight(left) * weight(right) || theta(left) - theta(right)||_2^2 / weight(parent)^2
          as outlined in [1]_
    splitter : {"best"}, default="best"
        The strategy used to choose the split at each node. Supported
        strategies are "best" to choose the best split.
    max_depth : int, default=None
        The maximum depth of the tree. If None, then nodes are expanded until
        all leaves are pure or until all leaves contain less than
        min_samples_split samples.
    min_samples_split : int or float, default=2
        The minimum number of samples required to split an internal node:
        - If int, then consider `min_samples_split` as the minimum number.
        - If float, then `min_samples_split` is a fraction and
          `ceil(min_samples_split * n_samples)` are the minimum
          number of samples for each split.
    min_samples_leaf : int or float, default=1
        The minimum number of samples required to be at a leaf node.
        A split point at any depth will only be considered if it leaves at
        least ``min_samples_leaf`` training samples in each of the left and
        right branches.  This may have the effect of smoothing the model,
        especially in regression.
        - If int, then consider `min_samples_leaf` as the minimum number.
        - If float, then `min_samples_leaf` is a fraction and
          `ceil(min_samples_leaf * n_samples)` are the minimum
          number of samples for each node.
    min_weight_fraction_leaf : float, default=0.0
        The minimum weighted fraction of the sum total of weights (of all
        the input samples) required to be at a leaf node. Samples have
        equal weight when sample_weight is not provided.
    min_var_leaf : ,

    min_var_leaf_on_val : ,

    max_features : int, float or {"auto", "sqrt", "log2"}, default=None
        The number of features to consider when looking for the best split:
        - If int, then consider `max_features` features at each split.
        - If float, then `max_features` is a fraction and
          `int(max_features * n_features)` features are considered at each
          split.
        - If "auto", then `max_features=n_features`.
        - If "sqrt", then `max_features=sqrt(n_features)`.
        - If "log2", then `max_features=log2(n_features)`.
        - If None, then `max_features=n_features`.
        Note: the search for a split does not stop until at least one
        valid partition of the node samples is found, even if it requires to
        effectively inspect more than ``max_features`` features.
    random_state : int, RandomState instance or None, default=None
        Controls the randomness of the estimator. The features are always
        randomly permuted at each split, even if ``splitter`` is set to
        ``"best"``. When ``max_features < n_features``, the algorithm will
        select ``max_features`` at random at each split before finding the best
        split among them. But the best found split may vary across different
        runs, even if ``max_features=n_features``. That is the case, if the
        improvement of the criterion is identical for several splits and one
        split has to be selected at random. To obtain a deterministic behaviour
        during fitting, ``random_state`` has to be fixed to an integer.
    min_impurity_decrease : float, default=0.0
        A node will be split if this split induces a decrease of the impurity
        greater than or equal to this value.
        The weighted impurity decrease equation is the following::
            N_t / N * (impurity - N_t_R / N_t * right_impurity
                                - N_t_L / N_t * left_impurity)
        where ``N`` is the total number of samples, ``N_t`` is the number of
        samples at the current node, ``N_t_L`` is the number of samples in the
        left child, and ``N_t_R`` is the number of samples in the right child.
        ``N``, ``N_t``, ``N_t_R`` and ``N_t_L`` all refer to the weighted sum,
        if ``sample_weight`` is passed.
    min_balancedness_tol:,

    honest: ,

    Attributes
    ----------
    feature_importances_ : ndarray of shape (n_features,)
        The feature importances.
        The higher, the more important the feature.
        The importance of a feature is computed as the
        (normalized) total reduction of the criterion brought
        by that feature. It is also known as the Gini importance [4]_.
        Warning: impurity-based feature importances can be misleading for
        high cardinality features (many unique values). See
        :func:`sklearn.inspection.permutation_importance` as an alternative.
    max_features_ : int
        The inferred value of max_features.
    n_features_ : int
        The number of features when ``fit`` is performed.
    n_outputs_ : int
        The number of outputs when ``fit`` is performed.
    tree_ : Tree instance
        The underlying Tree object. Please refer to
        ``help(econml.tree._tree.Tree)`` for attributes of Tree object.

    References
    ----------
    .. [1] Athey, Susan, Julie Tibshirani, and Stefan Wager. "Generalized random forests."
        The Annals of Statistics 47.2 (2019): 1148-1178
        https://arxiv.org/pdf/1610.01271.pdf

    """

    def __init__(self, *,
                 criterion="mse",
                 splitter="best",
                 max_depth=None,
                 min_samples_split=2,
                 min_samples_leaf=1,
                 min_weight_fraction_leaf=0.,
                 min_var_leaf=None,
                 min_var_leaf_on_val=False,
                 max_features=None,
                 random_state=None,
                 min_impurity_decrease=0.,
                 min_balancedness_tol=0.45,
                 honest=True):
        self.criterion = criterion
        self.splitter = splitter
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.min_samples_leaf = min_samples_leaf
        self.min_weight_fraction_leaf = min_weight_fraction_leaf
        self.min_var_leaf = min_var_leaf
        self.min_var_leaf_on_val = min_var_leaf_on_val
        self.max_features = max_features
        self.random_state = random_state
        self.min_impurity_decrease = min_impurity_decrease
        self.min_balancedness_tol = min_balancedness_tol
        self.honest = honest

    def get_depth(self):
        """Return the depth of the decision tree.
        The depth of a tree is the maximum distance between the root
        and any leaf.
        Returns
        -------
        self.tree_.max_depth : int
            The maximum depth of the tree.
        """
        check_is_fitted(self)
        return self.tree_.max_depth

    def get_n_leaves(self):
        """Return the number of leaves of the decision tree.
        Returns
        -------
        self.tree_.n_leaves : int
            Number of leaves.
        """
        check_is_fitted(self)
        return self.tree_.n_leaves

    def init(self,):
        """ This method should be called before fit. We added this pre-fit step so that this step
        can be executed without parallelism as it contains code that holds the gil and can hinder
        parallel execution. We also did not merge this step to __init__ as we want __init__ to just
        be storing the parameters for easy cloning. We also don't want to directly pass a RandomState
        object as random_state, as we want to keep the starting seed to be able to replicate the
        randomness of the object outside the object.
        """
        self.random_seed_ = self.random_state
        self.random_state_ = check_random_state(self.random_seed_)
        return self

    def fit(self, X, y, n_y, n_outputs, n_relevant_outputs, sample_weight=None, check_input=True):

        random_state = self.random_state_

        # Determine output settings
        n_samples, self.n_features_ = X.shape
        self.n_outputs_ = n_outputs
        self.n_relevant_outputs_ = n_relevant_outputs
        self.n_y_ = n_y
        self.n_samples_ = n_samples
        self.honest_ = self.honest

        # Important: This must be the first invocation of the random state at fit time, so that
        # train/test splits are re-generatable from an external object simply by knowing the
        # random_state parameter of the tree. Can be useful in the future if one wants to create local
        # linear predictions. Currently is also useful for testing.
        inds = np.arange(n_samples, dtype=np.intp)
        if self.honest:
            random_state.shuffle(inds)
            samples_train, samples_val = inds[:n_samples // 2], inds[n_samples // 2:]
        else:
            samples_train, samples_val = inds, inds

        if check_input:
            if getattr(y, "dtype", None) != DOUBLE or not y.flags.contiguous:
                y = np.ascontiguousarray(y, dtype=DOUBLE)
            y = np.atleast_1d(y)
            if y.ndim == 1:
                # reshape is necessary to preserve the data contiguity against vs
                # [:, np.newaxis] that does not.
                y = np.reshape(y, (-1, 1))
            if len(y) != n_samples:
                raise ValueError("Number of labels=%d does not match "
                                 "number of samples=%d" % (len(y), n_samples))

            if (sample_weight is not None):
                sample_weight = _check_sample_weight(sample_weight, X, DOUBLE)

        # Check parameters
        max_depth = (np.iinfo(np.int32).max if self.max_depth is None
                     else self.max_depth)

        if isinstance(self.min_samples_leaf, numbers.Integral):
            if not 1 <= self.min_samples_leaf:
                raise ValueError("min_samples_leaf must be at least 1 "
                                 "or in (0, 0.5], got %s"
                                 % self.min_samples_leaf)
            min_samples_leaf = self.min_samples_leaf
        else:  # float
            if not 0. < self.min_samples_leaf <= 0.5:
                raise ValueError("min_samples_leaf must be at least 1 "
                                 "or in (0, 0.5], got %s"
                                 % self.min_samples_leaf)
            min_samples_leaf = int(ceil(self.min_samples_leaf * n_samples))

        if isinstance(self.min_samples_split, numbers.Integral):
            if not 2 <= self.min_samples_split:
                raise ValueError("min_samples_split must be an integer "
                                 "greater than 1 or a float in (0.0, 1.0]; "
                                 "got the integer %s"
                                 % self.min_samples_split)
            min_samples_split = self.min_samples_split
        else:  # float
            if not 0. < self.min_samples_split <= 1.:
                raise ValueError("min_samples_split must be an integer "
                                 "greater than 1 or a float in (0.0, 1.0]; "
                                 "got the float %s"
                                 % self.min_samples_split)
            min_samples_split = int(ceil(self.min_samples_split * n_samples))
            min_samples_split = max(2, min_samples_split)

        min_samples_split = max(min_samples_split, 2 * min_samples_leaf)

        if isinstance(self.max_features, str):
            if self.max_features == "auto":
                max_features = self.n_features_
            elif self.max_features == "sqrt":
                max_features = max(1, int(np.sqrt(self.n_features_)))
            elif self.max_features == "log2":
                max_features = max(1, int(np.log2(self.n_features_)))
            else:
                raise ValueError("Invalid value for max_features. "
                                 "Allowed string values are 'auto', "
                                 "'sqrt' or 'log2'.")
        elif self.max_features is None:
            max_features = self.n_features_
        elif isinstance(self.max_features, numbers.Integral):
            max_features = self.max_features
        else:  # float
            if self.max_features > 0.0:
                max_features = max(1,
                                   int(self.max_features * self.n_features_))
            else:
                max_features = 0

        self.max_features_ = max_features

        if not 0 <= self.min_weight_fraction_leaf <= 0.5:
            raise ValueError("min_weight_fraction_leaf must in [0, 0.5]")
        if max_depth < 0:
            raise ValueError("max_depth must be greater than or equal to zero. ")
        if not (0 < max_features <= self.n_features_):
            raise ValueError("max_features must be in (0, n_features]")
        if not 0 <= self.min_balancedness_tol <= 0.5:
            raise ValueError("min_balancedness_tol must be in [0, 0.5]")

        if self.min_var_leaf is None:
            min_var_leaf = -1.0
        elif isinstance(self.min_var_leaf, numbers.Real) and (self.min_var_leaf >= 0.0):
            min_var_leaf = self.min_var_leaf
        else:
            raise ValueError("min_var_leaf must be either None or a real in [0, infinity). "
                             "Got {}".format(self.min_var_leaf))
        if not isinstance(self.min_var_leaf_on_val, bool):
            raise ValueError("min_var_leaf_on_val must be either True or False. "
                             "Got {}".format(self.min_var_leaf_on_val))

        # Set min_weight_leaf from min_weight_fraction_leaf
        if sample_weight is None:
            min_weight_leaf = (self.min_weight_fraction_leaf *
                               n_samples)
        else:
            min_weight_leaf = (self.min_weight_fraction_leaf *
                               np.sum(sample_weight))

        # Build tree
        max_train = len(samples_train) if sample_weight is None else np.count_nonzero(sample_weight[samples_train])
        if self.honest:
            max_val = len(samples_val) if sample_weight is None else np.count_nonzero(sample_weight[samples_val])
        if callable(self.criterion):
            criterion = self.criterion(self.n_outputs_, self.n_relevant_outputs_, self.n_features_, self.n_y_,
                                       n_samples, max_train,
                                       random_state.randint(np.iinfo(np.int32).max))
            if not isinstance(criterion, Criterion):
                raise ValueError("Input criterion is not a valid criterion")
            if self.honest:
                criterion_val = self.criterion(self.n_outputs_, self.n_relevant_outputs_, self.n_features_, self.n_y_,
                                               n_samples, max_val,
                                               random_state.randint(np.iinfo(np.int32).max))
            else:
                criterion_val = criterion
        else:
            criterion = CRITERIA_GRF[self.criterion](
                self.n_outputs_, self.n_relevant_outputs_, self.n_features_, self.n_y_, n_samples, max_train,
                random_state.randint(np.iinfo(np.int32).max))
            if self.honest:
                criterion_val = CRITERIA_GRF[self.criterion](
                    self.n_outputs_, self.n_relevant_outputs_, self.n_features_, self.n_y_, n_samples, max_val,
                    random_state.randint(np.iinfo(np.int32).max))
            else:
                criterion_val = criterion

        if (min_var_leaf >= 0.0 and (not isinstance(criterion, LinearMomentGRFCriterion))
                and (not isinstance(criterion_val, LinearMomentGRFCriterion))):
            raise ValueError("This criterion does not support min_var_leaf constraint!")

        splitter = self.splitter
        if not isinstance(self.splitter, Splitter):
            splitter = SPLITTERS[self.splitter](criterion, criterion_val,
                                                self.max_features_,
                                                min_samples_leaf,
                                                min_weight_leaf,
                                                self.min_balancedness_tol,
                                                self.honest,
                                                min_var_leaf,
                                                self.min_var_leaf_on_val,
                                                random_state.randint(np.iinfo(np.int32).max))

        self.tree_ = Tree(self.n_features_, self.n_outputs_, self.n_relevant_outputs_, store_jac=True)

        builder = DepthFirstTreeBuilder(splitter, min_samples_split,
                                        min_samples_leaf,
                                        min_weight_leaf,
                                        max_depth,
                                        self.min_impurity_decrease)
        builder.build(self.tree_, X, y, samples_train, samples_val,
                      sample_weight=sample_weight,
                      store_jac=True)

        return self

    def _validate_X_predict(self, X, check_input):
        """Validate X whenever one tries to predict, apply, predict_proba"""
        if check_input:
            X = check_array(X, dtype=DTYPE, accept_sparse=False)

        n_features = X.shape[1]
        if self.n_features_ != n_features:
            raise ValueError("Number of features of the model must "
                             "match the input. Model n_features is %s and "
                             "input n_features is %s "
                             % (self.n_features_, n_features))

        return X

    def get_train_test_split_inds(self,):
        check_is_fitted(self)
        random_state = check_random_state(self.random_seed_)
        inds = np.arange(self.n_samples_, dtype=np.intp)
        if self.honest_:
            random_state.shuffle(inds)
            return inds[:self.n_samples_ // 2], inds[self.n_samples_ // 2:]
        else:
            return inds, inds

    def predict(self, X, check_input=True):
        """Predict class or regression value for X.
        For a classification model, the predicted class for each sample in X is
        returned. For a regression model, the predicted value based on X is
        returned.
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            The input samples. Internally, it will be converted to
            ``dtype=np.float32`` and if a sparse matrix is provided
            to a sparse ``csr_matrix``.
        check_input : bool, default=True
            Allow to bypass several input checking.
            Don't use this parameter unless you know what you do.
        Returns
        -------
        y : array-like of shape (n_samples, n_outputs)
            The predicted classes, or the predict values.
        """
        check_is_fitted(self)
        X = self._validate_X_predict(X, check_input)
        pred = self.tree_.predict(X)
        return pred

    def predict_full(self, X, check_input=True):
        """Predict class or regression value for X.
        For a classification model, the predicted class for each sample in X is
        returned. For a regression model, the predicted value based on X is
        returned.
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            The input samples. Internally, it will be converted to
            ``dtype=np.float32`` and if a sparse matrix is provided
            to a sparse ``csr_matrix``.
        check_input : bool, default=True
            Allow to bypass several input checking.
            Don't use this parameter unless you know what you do.
        Returns
        -------
        y : array-like of shape (n_samples, n_outputs)
            The predicted classes, or the predict values.
        """
        check_is_fitted(self)
        X = self._validate_X_predict(X, check_input)
        pred = self.tree_.predict_full(X)
        return pred

    def predict_jac(self, X, check_input=True):
        """Predict class or regression value for X.
        For a classification model, the predicted class for each sample in X is
        returned. For a regression model, the predicted value based on X is
        returned.
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            The input samples. Internally, it will be converted to
            ``dtype=np.float32`` and if a sparse matrix is provided
            to a sparse ``csr_matrix``.
        check_input : bool, default=True
            Allow to bypass several input checking.
            Don't use this parameter unless you know what you do.
        Returns
        -------
        y : array-like of shape (n_samples,) or (n_samples, n_outputs)
            The predicted classes, or the predict values.
        """
        check_is_fitted(self)
        X = self._validate_X_predict(X, check_input)
        return self.tree_.predict_jac(X)

    def predict_alpha(self, X, check_input=True):
        """Predict class or regression value for X.
        For a classification model, the predicted class for each sample in X is
        returned. For a regression model, the predicted value based on X is
        returned.
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            The input samples. Internally, it will be converted to
            ``dtype=np.float32`` and if a sparse matrix is provided
            to a sparse ``csr_matrix``.
        check_input : bool, default=True
            Allow to bypass several input checking.
            Don't use this parameter unless you know what you do.
        Returns
        -------
        y : array-like of shape (n_samples,) or (n_samples, n_outputs)
            The predicted classes, or the predict values.
        """
        check_is_fitted(self)
        X = self._validate_X_predict(X, check_input)
        return self.tree_.predict_precond(X)

    def predict_alpha_and_jac(self, X, check_input=True):
        """Predict class or regression value for X.
        For a classification model, the predicted class for each sample in X is
        returned. For a regression model, the predicted value based on X is
        returned.
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            The input samples. Internally, it will be converted to
            ``dtype=np.float32`` and if a sparse matrix is provided
            to a sparse ``csr_matrix``.
        check_input : bool, default=True
            Allow to bypass several input checking.
            Don't use this parameter unless you know what you do.
        Returns
        -------
        y : array-like of shape (n_samples,) or (n_samples, n_outputs)
            The predicted classes, or the predict values.
        """
        check_is_fitted(self)
        X = self._validate_X_predict(X, check_input)
        return self.tree_.predict_precond_and_jac(X)

    def predict_moment(self, X, parameter, check_input=True):
        alpha, jac = self.predict_alpha_and_jac(X)
        return alpha - np.einsum('ijk,ik->ij', jac.reshape((-1, self.n_outputs_, self.n_outputs_)), parameter)

    def apply(self, X, check_input=True):
        """Return the index of the leaf that each sample is predicted as.
        .. versionadded:: 0.17
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            The input samples. Internally, it will be converted to
            ``dtype=np.float32`` and if a sparse matrix is provided
            to a sparse ``csr_matrix``.
        check_input : bool, default=True
            Allow to bypass several input checking.
            Don't use this parameter unless you know what you do.
        Returns
        -------
        X_leaves : array-like of shape (n_samples,)
            For each datapoint x in X, return the index of the leaf x
            ends up in. Leaves are numbered within
            ``[0; self.tree_.node_count)``, possibly with gaps in the
            numbering.
        """
        check_is_fitted(self)
        X = self._validate_X_predict(X, check_input)
        return self.tree_.apply(X)

    def decision_path(self, X, check_input=True):
        """Return the decision path in the tree.
        .. versionadded:: 0.18
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            The input samples. Internally, it will be converted to
            ``dtype=np.float32`` and if a sparse matrix is provided
            to a sparse ``csr_matrix``.
        check_input : bool, default=True
            Allow to bypass several input checking.
            Don't use this parameter unless you know what you do.
        Returns
        -------
        indicator : sparse matrix of shape (n_samples, n_nodes)
            Return a node indicator CSR matrix where non zero elements
            indicates that the samples goes through the nodes.
        """
        X = self._validate_X_predict(X, check_input)
        return self.tree_.decision_path(X)

    def feature_importances(self, max_depth=4, depth_decay_exponent=2.0):
        """Return the feature importances.
        The importance of a feature is computed as the (normalized) total
        reduction of the criterion brought by that feature.
        It is also known as the Gini importance.
        Warning: impurity-based feature importances can be misleading for
        high cardinality features (many unique values). See
        :func:`sklearn.inspection.permutation_importance` as an alternative.
        Returns
        -------
        feature_importances_ : ndarray of shape (n_features,)
            Normalized total reduction of criteria by feature
            (Gini importance).
        """
        check_is_fitted(self)

        return self.tree_.compute_feature_heterogeneity_importances(normalize=True, max_depth=max_depth,
                                                                    depth_decay=depth_decay_exponent)

    @property
    def feature_importances_(self):
        return self.feature_importances()
