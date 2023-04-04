################################################################################
# Copyright (c) 2022 ContinualAI.                                              #
# Copyrights licensed under the MIT License.                                   #
# See the accompanying LICENSE file for terms.                                 #
#                                                                              #
# Date: 11-04-2022                                                             #
# Author(s): Antonio Carta, Hamed Hemati                                       #
# E-mail: contact@continualai.org                                              #
# Website: avalanche.continualai.org                                           #
################################################################################
from copy import copy
from typing import Callable, Iterable, List, Union

import torch

from avalanche.benchmarks.scenarios.generic_scenario import (
    CLExperience,
    EagerCLStream,
    CLStream,
    ExperienceAttribute,
    CLScenario,
)
from avalanche.benchmarks.utils import classification_subset


class GradualOnlineCLExperience(CLExperience):
    """Gradual Online CL (OCL) Experience.

    GOCL experiences are created by splitting a larger experience. Therefore,
    they keep track of the original experience for logging purposes.
    """

    def __init__(
        self,
        current_experience: int = None,
        origin_stream=None,
        origin_experience=None,
        subexp_size: int = 1,
        is_first_subexp: bool = False,
        is_last_subexp: bool = False,
        sub_stream_length: int = None
    ):
        """Init.

        :param current_experience: experience identifier.
        :param origin_stream: origin stream.
        :param origin_experience: origin experience used to create self.
        :param is_first_subexp: whether self is the first in the sub-experiences
            stream.
        :param sub_stream_length: the sub-stream length.
        """
        super().__init__(current_experience, origin_stream)
        self.access_task_boundaries = False

        self.origin_experience = ExperienceAttribute(
            origin_experience, use_in_train=False
        )
        self.subexp_size = ExperienceAttribute(
            subexp_size, use_in_train=False
        )
        self.is_first_subexp = ExperienceAttribute(
            is_first_subexp, use_in_train=False
        )
        self.is_last_subexp = ExperienceAttribute(
            is_last_subexp, use_in_train=False
        )
        self.sub_stream_length = ExperienceAttribute(
            sub_stream_length, use_in_train=False
        )


def linear_transition(size_left, n_sub_exp, sub_exp_size):
    """Linear transition between two experiences."""
    # Fraction weights for the left experience with a linear decay.
    w = torch.linspace(1, 0, steps=n_sub_exp)

    # Calculate number of samples for the left experience.
    n_samples_l = [int(w[i].item()*sub_exp_size) for i in range(n_sub_exp)]
    # Add the remaining samples from the left experience.
    offset = 0
    while sum(n_samples_l) != size_left:
        i = offset % n_sub_exp
        if n_samples_l[i] < sub_exp_size:
            n_samples_l[i] += 1
        offset += 1
    # Add the samples from the right experience.
    n_samples_r = [sub_exp_size - n_samples_l[i] for i in range(n_sub_exp)]

    return zip(n_samples_l, n_samples_r)


def fixed_size_experience_split(
    stream: CLStream,
    experience_size: int,
    alpha: float = 0.25,
    tansition_type: str = "linear",
    shuffle: bool = True,
    drop_last: bool = False
):
    """Returns a lazy stream generated by splitting an experience into smaller
    ones.

    Splits the experience in smaller experiences of size `experience_size`.

    :param experience: The experience to split.
    :param experience_size: The experience size (number of instances).
    :param alpha: The amount of overlap between consecutive experiences. 
        It must be a value between 0.0 and 0.5. Defaults to 0.25.
    : param tansition_type: The type of transition between 
        consecutive experiences. Defaults to "linear".
    :param shuffle: If True, instances will be shuffled before splitting.
    :param drop_last: If True, the last mini-experience will be dropped if
        not of size `experience_size`
    :return: The list of datasets that will be used to create the
        mini-experiences.
    """
    class SubExperiencAbstract:
        """ Abstract class for a sub-experience.
            sub_exp_type: "single" or "combined"
        """

        def __init__(self, stream, sub_exp_type, indices_1,
                     indices_2, exp_id_left, exp_id_right):
            self.stream = stream  # reference to the stream
            self.sub_exp_type = sub_exp_type  # "single" or "combined"
            self.indices_1 = indices_1  # indices of the left experience
            self.indices_2 = indices_2  # indices of the right experience
            self.exp_id_left = exp_id_left  # indices of the left experience
            self.exp_id_right = exp_id_right  # indices of the right experience

        @ property
        def size(self):
            if self.sub_exp_type == "single":
                return len(self.indices_1)
            return len(self.indices_1) + len(self.indices_2)

    # Initialize shuffled list of indices for each experience dataset
    if shuffle:
        all_indices = {i: torch.arange(0, len(exp.dataset)) 
                       for i, exp in enumerate(stream)}
    else:
        all_indices = {i: torch.randperm(len(exp.dataset)) 
                       for i, exp in enumerate(stream)}

    # Initialize offsets for each experience dataset
    all_offsets = {i: 0 for i in range(len(stream))}

    # Final list of sub-experiences
    sub_experiences = []

    # For each experience in the stream, create sub-experiences
    # for the middle fraction and for the left and right fractions if possible
    for exp_id, experience in enumerate(stream):
        # --------------------> Middle fraction
        # Sub-experiences for the middle fraction
        size_cur_middle = len(experience.dataset) - 2 * \
            int(len(experience.dataset) * alpha)

        # For the first and last experiences experiences, we only mix 
        # in one side
        if exp_id == 0 or exp_id == len(stream) - 1:
            size_cur_middle += int(len(experience.dataset) * alpha)

        rem_cur_middle = size_cur_middle % experience_size
        size_cur_middle += (experience_size - rem_cur_middle)

        # Split the middle fraction into sub-experiences of "single" type
        o_m = all_offsets[exp_id]
        indices_middle = all_indices[exp_id][o_m:o_m + size_cur_middle]
        for i in range(0, len(indices_middle), experience_size):
            sub_experiences.append(
                SubExperiencAbstract(stream, "single",
                                     indices_middle[i:i+experience_size],
                                     None, exp_id, None))

        all_offsets[exp_id] += size_cur_middle

        if exp_id == len(stream) - 1:
            continue

        # --------------------> Overlap fraction

        # Sub-experiences for the overlap of the right fraction of the 
        # current experience and the left fraction of the next experience
        size_cur_right = len(experience.dataset) - size_cur_middle
        size_next_left = int(len(stream[exp_id+1].dataset) * alpha)
        rem_next_left = (size_cur_right + size_next_left) % experience_size
        size_next_left = size_next_left + (experience_size - rem_next_left)

        n_sub_exp = (size_cur_right + size_next_left) // experience_size
        if tansition_type == "linear":
            n_sub_exp_samples = linear_transition(size_cur_right, n_sub_exp, 
                                                  experience_size)
        else:
            raise ValueError("Transition type not supported.")

        for n_l, n_r in n_sub_exp_samples:
            o_l = all_offsets[exp_id]
            indices_cur_right = all_indices[exp_id][o_l:o_l + n_l]
            o_r = all_offsets[exp_id+1]
            indices_next_left = all_indices[exp_id+1][o_r:o_r + n_r]
            sub_experiences.append(
                SubExperiencAbstract(stream, "combined",
                                     indices_cur_right, indices_next_left,
                                     exp_id, exp_id+1))

            all_offsets[exp_id] += n_l
            all_offsets[exp_id+1] += n_r

    def gen():
        # Total number of sub-experiences
        sub_stream_length = len(sub_experiences)

        # Initialize all datasets and targets
        sub_exp = sub_experiences[0]
        all_ds = [sub_exp.stream[i].dataset for i in range(len(sub_exp.stream))]
        all_targets = [torch.LongTensor(sub_exp.stream[i].dataset.targets) 
                       for i in range(len(sub_exp.stream))]

        # Loop over sub-experiences
        init_idx = 0
        is_first_subexp = True
        while init_idx < len(sub_experiences):
            # Current sub-experience
            sub_exp = sub_experiences[init_idx]

            # Create GradualOnlineCLExperience instance
            exp = GradualOnlineCLExperience(
                origin_experience=None,
                subexp_size=sub_exp.size,
                is_first_subexp=is_first_subexp,
                sub_stream_length=sub_stream_length
            )

            # Set dataset and other attributes based on the sub-experience type
            if sub_exp.sub_exp_type == "single":
                exp.dataset = all_ds[sub_exp.exp_id_left
                                     ].subset(sub_exp.indices_1)
                exp.task_labels = [sub_exp.exp_id_left]
                unique_classes = all_targets[
                    sub_exp.exp_id_left][sub_exp.indices_1].unique().numpy()
                exp.classes_in_this_experience = unique_classes
            else:
                dataset = all_ds[sub_exp.exp_id_left
                                 ].subset(list(sub_exp.indices_1.numpy()))
                targets = all_targets[sub_exp.exp_id_left
                                      ][sub_exp.indices_1].unique()
                tasks = [sub_exp.exp_id_left]
                if len(sub_exp.indices_2) > 0:
                    dataset_r = all_ds[sub_exp.exp_id_right].subset(
                        list(sub_exp.indices_2.numpy()))
                    targets_r = all_targets[sub_exp.exp_id_right][
                        sub_exp.indices_2].unique()
                    targets = torch.cat([targets, targets_r], dim=0)

                    dataset = dataset.concat(dataset_r)

                exp.dataset = dataset
                exp.task_labels = tasks
                exp.classes_in_this_experience = targets.numpy()

            # is_first = False
            if is_first_subexp:
                is_first_subexp = False
            init_idx += 1
            yield exp

    return gen()


def split_online_stream(
    original_stream: EagerCLStream,
    experience_size: int,
    alpha: float = 0.25,
    tansition_type: str = "linear",
    shuffle: bool = False,
    drop_last: bool = False,
    experience_split_strategy: Callable[
        [CLExperience], Iterable[CLExperience]
    ] = None
):
    """Split a stream of large batches to create an online stream of small
    mini-batches.

    The resulting stream can be used for Online Continual Learning (OCL)
    scenarios (or data-incremental, or other online-based settings).

    For efficiency reasons, the resulting stream is an iterator, generating
    experience on-demand.

    :param original_stream: The stream with the original data.
    :param experience_size: The size of the experience, as an int. Ignored
        if `custom_split_strategy` is used.
    :param alpha: The amount of overlap between consecutive experiences. 
        It must be a value between 0.0 and 0.5. Defaults to 0.25.
    : param tansition_type: The type of transition between 
        consecutive experiences. Defaults to "linear".
    :param shuffle: If True, experiences will be split by first shuffling
        instances in each experience. This will use the default PyTorch
        random number generator at its current state. Defaults to False.
        Ignored if `experience_split_strategy` is used.
    :param drop_last: If True, if the last experience doesn't contain
        `experience_size` instances, then the last experience will be dropped.
        Defaults to False. Ignored if `experience_split_strategy` is used.
    :param experience_split_strategy: A function that implements a custom
        splitting strategy. The function must accept an experience and return an
        experience's iterator. Defaults to None, which means
        that the standard splitting strategy will be used (which creates
        experiences of size `experience_size`).
        A good starting to understand the mechanism is to look at the
        implementation of the standard splitting function
        :func:`fixed_size_experience_split_strategy`.
    :return: A lazy online stream with experiences of size `experience_size`.
    """
    if experience_split_strategy is None:

        def split_foo(exp: CLExperience, size: int):
            return fixed_size_experience_split(
                exp,
                size,
                alpha,
                tansition_type,
                shuffle,
                drop_last
            )

    # An iterator that generates sub-experiences from the original stream
    def exps_iter():
        for sub_exp in split_foo(original_stream, experience_size):
            yield sub_exp

    stream_name = (
        original_stream.name if hasattr(original_stream, "name") else "train"
    )
    return CLStream(
        name=stream_name, exps_iter=exps_iter(), set_stream_info=True
    )


class GradualOnlineCLScenario(CLScenario):
    def __init__(
        self,
        original_streams: List[EagerCLStream],
        experiences: Iterable[CLExperience] = None,
        experience_size: int = 10,
        alpha: float = 0.25,
        tansition_type: str = "linear",
        shuffle: bool = False,
        stream_split_strategy="fixed_size_split"
    ):
        """Creates an online scenario from an existing CL scenario

        :param original_streams: The streams from the original CL scenario.
        :param experiences: If None, the online stream will be created
            from the `train_stream` of the original CL scenario, otherwise it
            will create an online stream from the given sequence of experiences.
        :param experience_size: The size of each online experiences, as an int.
            Ignored if `custom_split_strategy` is used.
        :param alpha: The amount of overlap between consecutive experiences. 
            It must be a value between 0.0 and 0.5. Defaults to 0.25.
        : param tansition_type: The type of transition between consecutive 
            experiences. Defaults to "linear".
        :param shuffle: If True, samples will be shuffled before splitting. 
            Defaults to False.
        :param experience_split_strategy: A function that implements a custom
            splitting strategy. The function must accept an experience and
            return an experience's iterator. Defaults to None, which means
            that the standard splitting strategy will be used (which creates
            experiences of size `experience_size`).
            A good starting to understand the mechanism is to look at the
            implementation of the standard splitting function
            :func:`fixed_size_experience_split_strategy`.
        """
        if stream_split_strategy == "fixed_size_split":

            def split_foo(s):
                return split_online_stream(
                    s,
                    experience_size,
                    alpha,
                    tansition_type,
                    shuffle
                )

        else:
            raise ValueError("Unknown experience split strategy")

        streams_dict = {s.name: s for s in original_streams}
        if "train" not in streams_dict:
            raise ValueError("Missing train stream for `original_streams`.")
        if experiences is None:
            online_train_stream = split_foo(streams_dict["train"])
        else:
            assert len(experiences) > 1, "At least two experiences are needed."
            online_train_stream = split_foo(experiences)

        streams = [online_train_stream]
        for s in original_streams:
            s = copy(s)
            name_before = s.name

            # Set attributes of the new stream
            s.name = "original_" + s.name
            s.benchmark.stream_definitions[
                s.name
            ] = s.benchmark.stream_definitions[name_before]
            setattr(
                s.benchmark,
                f"{s.name}_stream",
                getattr(s.benchmark, f"{name_before}_stream"),
            )

            streams.append(s)

        super().__init__(streams)
