# -*- coding: utf-8 -*-
# @Date    : 2017/10/21
# @Author  : hrwhisper
import abc
import os
import time

import pandas as pd
import numpy as np
from scipy import sparse
from sklearn.ensemble import RandomForestClassifier
from sklearn.externals import joblib
from sklearn.metrics import accuracy_score

from parse_data import read_test_data, read_train_join_mall


def train_test_split(X, y, test_size=0.2):
    train_size = int((1 - test_size) * X.shape[0])
    if isinstance(X, np.ndarray):
        return X[:train_size], X[train_size:], y[:train_size], y[train_size:]
    else:
        return X.iloc[:train_size], X.iloc[train_size:], y.iloc[:train_size], y.iloc[train_size:]


def train_test_split_by_date(X, y):
    mask = X['time_stamp'] >= '2017-08-18'
    return X.loc[mask], X.loc[~mask], y.loc[mask], y.loc[~mask]


def safe_dump_model(model, save_path, compress=3):
    print('save model......')
    dir_name = os.path.dirname(save_path)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    joblib.dump(model, save_path, compress=compress)
    print('save model done.')


def safe_save_csv_result(res, save_path):
    dir_name = os.path.dirname(save_path)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    res.to_csv(save_path)


def get_recommend_cpu_count():
    """
        windows: 只跑一半
        linux: 为我的测试机或者服务器
    """
    t = os.cpu_count()
    if os.name == 'nt':  return t // 2
    if t >= 32:
        return t // 8 * 5 - 1
    else:
        return t - 1


class XXToVec(abc.ABC):
    def __init__(self, feature_save_path):
        self.FEATURE_SAVE_PATH = feature_save_path

    @abc.abstractclassmethod
    def _fit_transform(self, train_data, mall_id):
        pass

    @abc.abstractclassmethod
    def _transform(self, test_data, mall_id):
        pass

    def fit_transform(self, train_data, mall_id, renew=True, should_save=False):
        """

        :param train_data:
        :param mall_id:
        :param renew
        :param should_save:
        :return:
        """
        if renew:
            # train_data = train_data.loc[train_data['mall_id'] == mall_id]
            features = self._fit_transform(train_data, mall_id)
            if should_save:
                safe_dump_model(features, self.FEATURE_SAVE_PATH.format('train', mall_id))
        else:
            features = joblib.load(self.FEATURE_SAVE_PATH.format('train', mall_id))
        return features

    def transform(self, test_data, mall_id, renew=True, should_save=False):
        """

        :param test_data:
        :param mall_id:
        :param renew
        :param should_save:
        :return:
        """
        if renew:
            # test_data = test_data.loc[test_data['mall_id'] == mall_id]
            features = self._transform(test_data, mall_id)
            if should_save:
                safe_dump_model(features, self.FEATURE_SAVE_PATH.format('test', mall_id))
        else:
            features = joblib.load(self.FEATURE_SAVE_PATH.format('test', mall_id))
        return features


class DataVector(object):
    @staticmethod
    def data_to_vec(mall_id, vec_func, data, label=None, is_train=True):
        cur_index = data['mall_id'] == mall_id
        y = label[cur_index] if label is not None else None
        data = data.loc[cur_index]
        funcs = [func.fit_transform if is_train else func.transform for func in vec_func]
        vectors = [func(data, mall_id) for func in funcs]
        X = sparse.hstack(vectors)
        return X, y

    @staticmethod
    def train_and_test_to_vec(mall_id, vec_func, train_data, train_label, test_data, test_label=None):
        X_train, y_train = DataVector.data_to_vec(mall_id, vec_func, train_data, train_label)
        X_test, y_test = DataVector.data_to_vec(mall_id, vec_func, test_data, test_label, is_train=False)
        return X_train, y_train, X_test, y_test


class ModelBase(object):
    """
        多分类
        划分训练集依据： 总体按时间排序后20%
    """

    def __init__(self, test_ratio=0.2, random_state=42, n_jobs=None, use_multiprocess=False, save_model=False,
                 save_result_proba=False, save_model_base_path='./model_save/', result_save_base_path='./result_save/'):
        self._test_ratio = test_ratio
        self._random_state = random_state
        self.n_jobs = get_recommend_cpu_count() if n_jobs is None else n_jobs
        self.use_multiprocess = use_multiprocess
        self.SAVE_MODEL = save_model
        self.SAVE_RESULT_PROBA = save_result_proba
        self.SAVE_MODEL_BASE_PATH = save_model_base_path
        self.RESULT_SAVE_BASE_PATH = result_save_base_path

    def get_name(self):
        return self.__class__.__name__

    def _get_classifiers(self):
        """
        :return: dict. {name:classifier}
        """
        return {
            'random forest': RandomForestClassifier(n_jobs=self.n_jobs, n_estimators=400, bootstrap=False,
                                                    random_state=self._random_state, class_weight='balanced'),
        }

    @staticmethod
    def trained_and_predict_location(clf, X_train, y_train, X_test, y_test=None, predicted_proba=False):
        print('fitting....')
        clf = clf.fit(X_train, y_train)
        print('predict....')
        return clf.predict(X_test) if not predicted_proba else clf.predict_proba(X_test)


    def _single_trained_by_mall_and_predict_location(self, vec_func, train_data, train_label, test_data,
                                                     test_label=None):
        ans = {}
        clf_report = {}
        is_train = test_label is not None
        for ri, mall_id in enumerate(train_data['mall_id'].unique()):
            X_train, y_train, X_test, y_test = DataVector.train_and_test_to_vec(mall_id, vec_func, train_data,
                                                                                train_label, test_data,
                                                                                test_label)
            classifiers = self._get_classifiers()
            for name, clf in classifiers.items():
                predicted = self.trained_and_predict_location(clf, X_train, y_train, X_test, y_test)
                if self.SAVE_MODEL:
                    safe_dump_model(clf, '{}/{}/{}_{}.pkl'.format(self.SAVE_MODEL_BASE_PATH, name,
                                                                  'train' if is_train else 'test', mall_id))

                index = test_data['mall_id'] == mall_id
                for row_id, label in zip(test_data[index]['row_id'], predicted):
                    ans[row_id] = label

                if self.SAVE_RESULT_PROBA:
                    predicted_pro = clf.predict_proba(X_test)
                    row_ids = pd.DataFrame(test_data[index]['row_id'].values, columns=['row_id'])
                    predicted_pro = pd.DataFrame(predicted_pro, columns=clf.classes_)

                    safe_save_csv_result(pd.concat([row_ids, predicted_pro], axis=1).set_index('row_id'),
                                         '{}/{}/{}_{}.csv'.format(self.RESULT_SAVE_BASE_PATH, name,
                                                                  'train' if is_train else 'test', mall_id))

                if is_train:
                    score = accuracy_score(y_test, predicted)
                    clf_report[name] = clf_report.get(name, 0) + score
                    print(ri, mall_id, name, score)
                else:
                    print(ri, mall_id)

        if is_train:
            cnt = train_data['mall_id'].unique().shape[0]
            classifiers = self._get_classifiers()
            for name, score in clf_report.items():
                print("{} Mean: {}".format(classifiers[name], score / cnt))
        return ans

    def _trained_by_mall_and_predict_location(self, vec_func, train_data, train_label, test_data, test_label=None):
        """

        :param vec_func:
        :param train_data:
        :param train_label
        :param test_data:
        :param test_label:
        :return:
        """
        return self._single_trained_by_mall_and_predict_location(vec_func, train_data, train_label, test_data,
                                                                     test_label)

    def train_test(self, vec_func, target_column='shop_id'):
        """

        :param vec_func: list of vector function
        :param target_column: the target column you want to predict.
        :return:
        """
        # ------input data -----------
        train_data = read_train_join_mall()
        train_data = train_data.sort_values(by='time_stamp')
        train_label = train_data[target_column]
        train_data, test_data, train_label, test_label = train_test_split(train_data, train_label, self._test_ratio)

        ans = self._trained_by_mall_and_predict_location(vec_func, train_data, train_label, test_data, test_label)

    def train_and_on_test_data(self, vec_func, target_column='shop_id'):
        train_data = read_train_join_mall()
        train_label = train_data[target_column]
        test_data = read_test_data()

        ans = self._trained_by_mall_and_predict_location(vec_func, train_data, train_label, test_data)
        self.result_to_csv(ans, test_data)

    @staticmethod
    def result_to_csv(ans, test_data=None):
        _save_path = './result'
        if not os.path.exists(_save_path):
            os.mkdir(_save_path)
        with open(_save_path + '/hrwhisper_res_{}.csv'.format(time.strftime("%Y-%m-%d-%H-%M-%S")), 'w') as f:
            f.write('row_id,shop_id\n')
            if test_data is not None:
                for row_id in test_data['row_id']:
                    f.write('{},{}\n'.format(row_id, ans[row_id]))
            else:
                for row_id, shop_id in ans.items():
                    f.write('{},{}\n'.format(row_id, shop_id))
        print('done')
