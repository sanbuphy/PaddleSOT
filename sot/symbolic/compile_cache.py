import paddle

from ..utils import Cache, GraphLogger, Singleton
from .interpreter import compile_sir


def clear_eager_tensor_name(output_tensors):
    for output_tensor in output_tensors:
        output_tensor.name = ""


class FallbackWrapper:
    def __init__(self, compile_sir):
        self.compile_sir = compile_sir
        self.partial_program = None
        self.concrete_program = None

    def __call__(self, *args, **kwargs):
        frame_callback = paddle.fluid.core.set_eval_frame(None)
        """ TODO: we disable partial_program cache here because some bugs in ast to_static.
            >>> def func(x, y):
            >>>     return x + y

            if we call with f(tx, tx) and then f(tx, ty), we get wrong answer, because caches is hit but should not.
            we get a function: f x = 2 * x .

            we use `and False` to disable this cache.
        """
        # TODO(zmh): modify the if
        if self.partial_program is None or True:
            outputs = self.compile_sir(*args, **kwargs)
            (
                self.concrete_program,
                self.partial_program,
            ) = self.compile_sir.get_concrete_program(*args, **kwargs)
        else:
            # Speed up Resnet from 0.0068 --> 0.0057
            outputs = self.partial_program(*args, **kwargs)
        clear_eager_tensor_name(outputs)

        program = self.concrete_program.main_program

        GraphLogger().add_subgraph(program)

        paddle.fluid.core.set_eval_frame(frame_callback)
        return outputs


@Singleton
class CompileSIRCache(Cache):
    def __init__(self):
        super().__init__(weak=False)

    def key_fn(self, context, sir_name, build_strategy):
        sir = context.get_sir(sir_name)
        # NOTE(dev): Is str(sir) a heavy opearation ?
        hash_key = hash(str(sir))
        return hash_key

    def value_fn(self, context, sir_name, build_strategy):
        return FallbackWrapper(
            paddle.jit.to_static(
                compile_sir(context, sir_name),
                build_strategy=build_strategy,
                enable_fallback=False,
            )
        )
