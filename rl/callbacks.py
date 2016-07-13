import warnings
import timeit
import json
from tempfile import mkdtemp

import numpy as np

from keras.callbacks import Callback as KerasCallback, CallbackList as KerasCallbackList
from keras.utils.generic_utils import Progbar


class Callback(KerasCallback):
	def _set_env(self, env):
		self.env = env

	def on_episode_begin(self, episode, logs={}):
		pass

	def on_episode_end(self, episode, logs={}):
		pass

	def on_step_begin(self, step, logs={}):
		pass

	def on_step_end(self, step, logs={}):
		pass


class CallbackList(KerasCallbackList):
	def _set_env(self, env):
		for callback in self.callbacks:
			if callable(getattr(callback, '_set_env', None)):
				callback._set_env(env)

	def on_episode_begin(self, episode, logs={}):
		for callback in self.callbacks:
			# Check if callback supports the more appropriate `on_episode_begin` callback.
			# If not, fall back to `on_epoch_begin` to be compatible with built-in Keras callbacks.
			if callable(getattr(callback, 'on_episode_begin', None)):
				callback.on_episode_begin(episode, logs=logs)
			else:
				callback.on_epoch_begin(episode, logs=logs)

	def on_episode_end(self, episode, logs={}):
		for callback in self.callbacks:
			# Check if callback supports the more appropriate `on_episode_end` callback.
			# If not, fall back to `on_epoch_end` to be compatible with built-in Keras callbacks.
			if callable(getattr(callback, 'on_episode_end', None)):
				callback.on_episode_end(episode, logs=logs)
			else:
				callback.on_epoch_end(episode, logs=logs)

	def on_step_begin(self, step, logs={}):
		for callback in self.callbacks:
			# Check if callback supports the more appropriate `on_step_begin` callback.
			# If not, fall back to `on_batch_begin` to be compatible with built-in Keras callbacks.
			if callable(getattr(callback, 'on_step_begin', None)):
				callback.on_step_begin(step, logs=logs)
			else:
				callback.on_batch_begin(step, logs=logs)

	def on_step_end(self, step, logs={}):
		for callback in self.callbacks:
			# Check if callback supports the more appropriate `on_step_end` callback.
			# If not, fall back to `on_batch_end` to be compatible with built-in Keras callbacks.
			if callable(getattr(callback, 'on_step_end', None)):
				callback.on_step_end(step, logs=logs)
			else:
				callback.on_batch_end(step, logs=logs)


class TestLogger(Callback):
	def on_episode_end(self, episode, logs):
		template = 'Episode {0}: reward: {1:.3f}, steps: {2}'
		variables = [
			episode + 1,
			logs['episode_reward'],
			logs['nb_steps'],
		]
		print(template.format(*variables))


class TrainEpisodeLogger(Callback):
	def __init__(self):
		# Some algorithms compute multiple episodes at once since they are multi-threaded.
		# We therefore use a dictionary that is indexed by the episode to separate episodes
		# from each other.
		self.episode_start = {}
		self.observations = {}
		self.rewards = {}
		self.actions = {}
		self.metrics = {}
		self.step = 0

	def on_train_begin(self, logs):
		self.train_start = timeit.default_timer()
		self.metrics_names = self.model.metrics_names
		print('Training for {} steps ...'.format(self.params['nb_steps']))
		
	def on_train_end(self, logs):
		duration = timeit.default_timer() - self.train_start
		print('done, took {:.3f} seconds'.format(duration))

	def on_episode_begin(self, episode, logs):
		self.episode_start[episode] = timeit.default_timer()
		self.observations[episode] = []
		self.rewards[episode] = []
		self.actions[episode] = []
		self.metrics[episode] = []

	def on_episode_end(self, episode, logs):
		duration = timeit.default_timer() - self.episode_start[episode]
		episode_steps = len(self.observations[episode])

		# Format all metrics.
		metrics = np.array(self.metrics[episode])
		metrics_template = ''
		metrics_variables = []
		with warnings.catch_warnings():
			warnings.filterwarnings('error')
			for idx, name in enumerate(self.metrics_names):
				if idx > 0:
					metrics_template += ', '
				try:
					value = np.nanmean(metrics[:, idx])
					metrics_template += '{}: {:f}'
				except Warning:
					value = '--'
					metrics_template += '{}: {}'
				metrics_variables += [name, value]			
		metrics_text = metrics_template.format(*metrics_variables)

		nb_step_digits = str(int(np.ceil(np.log10(self.params['nb_steps']))) + 1)
		print nb_step_digits
		template = '{step: ' + nb_step_digits + 'd}/{nb_steps}: episode: {episode}, duration: {duration:.3f}s, episode steps: {episode_steps}, steps per second: {sps:.0f}, episode reward: {episode_reward:.3f}, mean reward: {reward_mean:.3f} [{reward_min:.3f}, {reward_max:.3f}], mean action: {action_mean:.3f} [{action_min:.3f}, {action_max:.3f}], mean observation: {obs_mean:.3f} [{obs_min:.3f}, {obs_max:.3f}], {metrics}'
		variables = {
		 	'step': self.step,
		 	'nb_steps': self.params['nb_steps'],
			'episode': episode + 1,
			'duration': duration,
			'episode_steps': episode_steps,
			'sps': float(episode_steps) / duration,
			'episode_reward': np.sum(self.rewards[episode]),
			'reward_mean': np.mean(self.rewards[episode]),
			'reward_min': np.min(self.rewards[episode]),
			'reward_max': np.max(self.rewards[episode]),
			'action_mean': np.mean(self.actions[episode]),
			'action_min': np.min(self.actions[episode]),
			'action_max': np.max(self.actions[episode]),
			'obs_mean': np.mean(self.observations[episode]),
			'obs_min': np.min(self.observations[episode]),
			'obs_max': np.max(self.observations[episode]),
			'metrics': metrics_text,
		}
		print(template.format(**variables))

		# Free up resources.
		del self.episode_start[episode]
		del self.observations[episode]
		del self.rewards[episode]
		del self.actions[episode]
		del self.metrics[episode]

	def on_step_end(self, step, logs):
		episode = logs['episode']
		self.observations[episode].append(logs['observation'])
		self.rewards[episode].append(logs['reward'])
		self.actions[episode].append(logs['action'])
		self.metrics[episode].append(logs['metrics'])
		self.step += 1


class TrainIntervalLogger(Callback):
	def __init__(self, interval=10000):
		self.interval = interval
		self.step = 0
		self.reset()

	def reset(self):
		self.interval_start = timeit.default_timer()
		self.progbar = Progbar(target=self.interval)
		self.metrics = []

	def on_train_begin(self, logs):
		self.train_start = timeit.default_timer()
		self.metrics_names = self.model.metrics_names
		print('Training for {} steps ...'.format(self.params['nb_steps']))

	def on_train_end(self, logs):
		duration = timeit.default_timer() - self.train_start
		print('done, took {:.3f} seconds'.format(duration))

	def on_step_begin(self, step, logs):
		if self.step % self.interval == 0:
			self.reset()
			print('Interval {} ({} steps performed)'.format(self.step / self.interval + 1, self.step))

	def on_step_end(self, step, logs):
		# TODO: work around nan's in metrics. This isn't really great yet and probably not 100% accurate
		filtered_metrics = []
		means = None
		for idx, value in enumerate(logs['metrics']):
			if not np.isnan(value):
				filtered_metrics.append(value)
			else:
				mean = np.nan
				if len(self.metrics) > 0 and not np.isnan(self.metrics).all():
					if means is None:
						means = np.nanmean(self.metrics, axis=0)
						assert means.shape == (len(self.metrics_names),)
					mean = means[idx]
				filtered_metrics.append(mean)

		values = [('reward', logs['reward'])]
		if not np.isnan(filtered_metrics).any():
			values += list(zip(self.metrics_names, filtered_metrics))
		self.progbar.update((self.step % self.interval) + 1, values=values)
		self.step += 1
		self.metrics.append(logs['metrics'])


class FileLogger(Callback):
	def __init__(self, filename, save_continiously=False):
		self.filename = filename
		self.save_continiously = save_continiously

		# Some algorithms compute multiple episodes at once since they are multi-threaded.
		# We therefore use a dict that maps from episode to metrics array.
		self.metrics = {}
		self.starts = {}
		self.data = {}

	def on_train_begin(self, logs):
		self.metrics_names = self.model.metrics_names
		self.file = open(self.filename, 'w')

	def on_train_end(self, logs):
		self.save_data()
		self.file.close()

	def on_episode_begin(self, episode, logs):
		assert episode not in self.metrics
		assert episode not in self.starts
		self.metrics[episode] = []
		self.starts[episode] = timeit.default_timer()

	def on_episode_end(self, episode, logs):
		duration = timeit.default_timer() - self.starts[episode]
		
		metrics = self.metrics[episode]
		if np.isnan(metrics).all():
			mean_metrics = np.array([np.nan for _ in self.metrics_names])
		else:
			mean_metrics = np.nanmean(metrics, axis=0)
		assert len(mean_metrics) == len(self.metrics_names)

		data = list(zip(self.metrics_names, mean_metrics))
		data += list(logs.iteritems())
		data += [('episode', episode), ('duration', duration)]
		for key, value in data:
			if key not in self.data:
				self.data[key] = []
			self.data[key].append(value)

		if self.save_continiously:
			self.save_data()

		# Clean up.
		del self.metrics[episode]
		del self.starts[episode]

	def on_step_end(self, step, logs):
		self.metrics[logs['episode']].append(logs['metrics'])

	def save_data(self):
		if len(self.data.keys()) == 0:
			return

		# Sort everything by episode.
		assert 'episode' in self.data
		sorted_indexes = np.argsort(self.data['episode'])
		sorted_data = {}
		for key, values in self.data.iteritems():
			assert len(self.data[key]) == len(sorted_indexes)
			sorted_data[key] = [self.data[key][idx] for idx in sorted_indexes]

		# Overwrite already open file. We can simply seek to the beginning since the file will
		# grow strictly monotonously.
		self.file.seek(0)
		json.dump(sorted_data, self.file)


class Visualizer(Callback):
	def on_step_end(self, step, logs):
		self.env.render(mode='human')
