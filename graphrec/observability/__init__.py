"""Metrics, and the port they are served on.

Split out of `graphrec.http` because half the things that need to be measured
are not HTTP: a training run's duration and a job queue's depth are the
observations §24 asks for alerts on, and neither belongs in a middleware
package.
"""
