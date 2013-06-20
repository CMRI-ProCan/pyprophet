#encoding: latin-1

# openblas + multiprocessing crashes for OPENBLAS_NUM_THREADS > 1 !!!
import os
os.putenv("OPENBLAS_NUM_THREADS", "1")

try:
    profile
except:
    profile = lambda x: x

from data_handling import Experiment
from classifiers   import AbstractLearner

import numpy as np
from  stats import mean_and_std_dev, find_cutoff

class AbstractSemiSupervisedLearner(object):

    def start_semi_supervised_learning(self, train, config):
        raise NotImplementedError()

    def iter_semi_supervised_learning(self, train, config):
        raise NotImplementedError()

    def averaged_learner(self, params):
        raise NotImplementedError()

    def score(self, df, params):
        raise NotImplementedError()

    @profile
    def learn(self, experiment, config):
        assert isinstance(experiment, Experiment)
        assert isinstance(config, dict)

        fraction = config.get("xeval.fraction")
        num_xeval = config.get("xeval.num_iter")

        experiment.split_for_xval(fraction)
        train = experiment.get_train_peaks()

        train.rank_by("main_score")

        params, clf_scores = self.start_semi_supervised_learning(train, config)

        train.set_and_rerank("classifier_score", clf_scores)
        # semi supervised iteration:
        for inner in range(num_xeval):
            params, clf_scores = self.iter_semi_supervised_learning(train, config)
            train.set_and_rerank("classifier_score", clf_scores)

        # nach semi supervsised iter: classfiy full dataset
        clf_scores = self.score(experiment, params)
        mu, nu = mean_and_std_dev(clf_scores)
        experiment.set_and_rerank("classifier_score", clf_scores)

        td_scores = experiment.get_top_decoy_peaks()["classifier_score"]

        mu, nu = mean_and_std_dev(td_scores)
        experiment["classifier_score"] = (experiment["classifier_score"] - mu ) / nu
        experiment.rank_by("classifier_score")

        top_test_peaks = experiment.get_top_test_peaks()

        top_test_target_scores = top_test_peaks.get_target_peaks()["classifier_score"]
        top_test_decoy_scores = top_test_peaks.get_decoy_peaks()["classifier_score"]

        return top_test_target_scores, top_test_decoy_scores, params


class StandardSemiSupervisedLearner(AbstractSemiSupervisedLearner):

    def __init__(self, inner_learner):
        assert isinstance(inner_learner, AbstractLearner)
        self.inner_learner = inner_learner

    def select_train_peaks(self, train, sel_column, fdr, lambda_):
        assert isinstance(train, Experiment)
        assert isinstance(sel_column, basestring)
        assert isinstance(fdr, float)

        tt_peaks = train.get_top_target_peaks()
        tt_scores = tt_peaks[sel_column]
        td_peaks = train.get_top_decoy_peaks()
        td_scores = td_peaks[sel_column]

        # find cutoff fdr from scores and only use best target peaks:
        cutoff =  find_cutoff(tt_scores, td_scores, lambda_, fdr)
        best_target_peaks = tt_peaks.filter_(tt_scores >= cutoff)
        return td_peaks, best_target_peaks

    def start_semi_supervised_learning(self, train, config):
        fdr = config.get("semi_supervised_learner.initial_fdr")
        lambda_ = config.get("semi_supervised_learner.initial_lambda")
        td_peaks, bt_peaks = self.select_train_peaks(train, "main_score", fdr,
                lambda_)
        model = self.inner_learner.learn(td_peaks, bt_peaks, False)
        w = model.get_parameters()
        clf_scores = model.score(train, False)
        clf_scores -= np.mean(clf_scores)
        return w, clf_scores

    def iter_semi_supervised_learning(self, train, config):
        fdr = config.get("semi_supervised_learner.iteration_fdr")
        lambda_ = config.get("semi_supervised_learner.iteration_lambda")
        td_peaks, bt_peaks = self.select_train_peaks(train,
                                                     "classifier_score",
                                                     fdr, lambda_)

        model = self.inner_learner.learn(td_peaks, bt_peaks, True)
        w = model.get_parameters()
        clf_scores = model.score(train, True)
        return w, clf_scores

    def averaged_learner(self, params):
        return self.inner_learner.averaged_learner(params)

    def score(self, df, params):
        self.inner_learner.set_parameters(params)
        return self.inner_learner.score(df, True)


