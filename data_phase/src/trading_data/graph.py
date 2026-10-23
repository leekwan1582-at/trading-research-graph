from langgraph.graph import START, END, StateGraph
from trading_supervisor.supervisor import strategy_supervisor

from .agent import data_agent
from .contracts import DataAccess, DataState


def build_data_graph(*, access: DataAccess, include_supervisor: bool = True, checkpointer=None):
    builder = StateGraph(DataState)

    def prepare_data(state: DataState):
        return data_agent(state, access=access)

    builder.add_node('data_agent', prepare_data)
    if include_supervisor:
        builder.add_node('strategy_supervisor', strategy_supervisor)
        builder.add_edge(START, 'strategy_supervisor')
        builder.add_edge('strategy_supervisor', 'data_agent')
    else:
        builder.add_edge(START, 'data_agent')
    builder.add_edge('data_agent', END)
    return builder.compile(checkpointer=checkpointer)
