################################################################################
# Copyright (c) 2021 ContinualAI.                                              #
# Copyrights licensed under the MIT License.                                   #
# See the accompanying LICENSE file for terms.                                 #
#                                                                              #
# Date: 24-06-2020                                                             #
# Author(s): Gabriele Graffieti, Vincenzo Lomonaco                             #
# E-mail: contact@continualai.org                                              #
# Website: wwww.continualai.org                                                #
################################################################################

""" This module implements an high-level function to create the classic
Fashion MNIST split CL scenario. """

from typing import Sequence, Optional
from os.path import expanduser
from torchvision.datasets import FashionMNIST
from torchvision import transforms

from avalanche.benchmarks import nc_scenario
from avalanche.benchmarks.utils import train_test_transformation_datasets

_default_cifar10_train_transform = transforms.Compose([
    transforms.RandomCrop(32, padding=4),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465),
                         (0.2023, 0.1994, 0.2010))
])

_default_cifar10_test_transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465),
                         (0.2023, 0.1994, 0.2010))
])


def SplitFMNIST(n_experiences: int,
                first_batch_with_half_classes: bool = False,
                return_task_id=False,
                seed: Optional[int] = None,
                fixed_class_order: Optional[Sequence[int]] = None,
                train_transform=_default_cifar10_train_transform,
                test_transform=_default_cifar10_test_transform
                ):
    """
    Creates a CL scenario using the Fashion MNIST dataset.
    If the dataset is not present in the computer the method automatically
    download it and store the data in the data folder.

    :param n_experiences: The number of experiences in the current
        scenario. If the first experience is a "pretraining" step and it
        contains half of the classes. The value of this parameter should be a
        divisor of 10 if first_task_with_half_classes if false, a divisor of 5
        otherwise.
    :param first_batch_with_half_classes: A boolean value that indicates if a
        first pretraining batch containing half of the classes should be used.
        If it's True, a pretraining batch with half of the classes (5 for
        cifar100) is used. If this parameter is False no pretraining task
        will be used, and the dataset is simply split into
        a the number of experiences defined by the parameter n_experiences.
        Default to False.
    :param return_task_id: if True, for every experience the task id is returned
        and the Scenario is Multi Task. This means that the scenario returned
        will be of type ``NCMultiTaskScenario``. If false the task index is
        not returned (default to 0 for every batch) and the returned scenario
        is of type ``NCSingleTaskScenario``.
    :param seed: A valid int used to initialize the random number generator.
        Can be None.
    :param fixed_class_order: A list of class IDs used to define the class
        order. If None, value of ``seed`` will be used to define the class
        order. If non-None, ``seed`` parameter will be ignored.
        Defaults to None.
    :param train_transform: The transformation to apply to the training data,
        e.g. a random crop, a normalization or a concatenation of different
        transformations (see torchvision.transform documentation for a
        comprehensive list of possible transformations).
        If no transformation is passed, the default train transformation
        will be used.
    :param test_transform: The transformation to apply to the test data,
        e.g. a random crop, a normalization or a concatenation of different
        transformations (see torchvision.transform documentation for a
        comprehensive list of possible transformations).
        If no transformation is passed, the default test transformation
        will be used.

    :returns: A :class:`NCMultiTaskScenario` instance initialized for the the
        MT scenario using CIFAR10 if the parameter ``return_task_id`` is True,
        a :class:`NCSingleTaskScenario` initialized for the SIT scenario using
        CIFAR10 otherwise.
    """
    cifar_train, cifar_test = _get_fmnist_dataset(
        train_transform, test_transform)

    if return_task_id:
        return nc_scenario(
            train_dataset=cifar_train,
            test_dataset=cifar_test,
            n_experiences=n_experiences,
            task_labels=True,
            seed=seed,
            fixed_class_order=fixed_class_order,
            per_exp_classes={0: 5} if first_batch_with_half_classes else None)
    else:
        return nc_scenario(
            train_dataset=cifar_train,
            test_dataset=cifar_test,
            n_experiences=n_experiences,
            task_labels=False,
            seed=seed,
            fixed_class_order=fixed_class_order,
            per_exp_classes={0: 5} if first_batch_with_half_classes else None)


def _get_fmnist_dataset(train_transformation, test_transformation):
    train_set = FashionMNIST(expanduser("~") + "/.avalanche/data/fashionmnist/",
                             train=True, download=True)
    test_set = FashionMNIST(expanduser("~") + "/.avalanche/data/fashionmnist/",
                            train=False, download=True)
    return train_test_transformation_datasets(
        train_set, test_set, train_transformation, test_transformation)


__all__ = [
    'SplitFMNIST'
]

if __name__ == "__main__":

    nc_scenario = SplitFMNIST(n_experiences=10)

    for i, batch in enumerate(nc_scenario.train_stream):
        print(i, batch)
