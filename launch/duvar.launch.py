from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    defaults = {
        'ileri_hiz': '2.0',
        'donus_hiz': '2.0',
        'alt_sinir': '1.0',
        'ust_sinir': '10.0',
    }
    arguments = [
        DeclareLaunchArgument(name, default_value=value)
        for name, value in defaults.items()
    ]
    simulator = Node(
        package='turtlesim',
        executable='turtlesim_node',
        output='screen',
        additional_env={'QT_QPA_PLATFORM': 'offscreen'},
    )
    controller = Node(
        package='turtle_duvar_py',
        executable='duvar_kacis',
        output='screen',
        parameters=[{
            name: ParameterValue(LaunchConfiguration(name), value_type=float)
            for name in defaults
        }],
    )
    close_all = RegisterEventHandler(OnProcessExit(
        target_action=controller,
        on_exit=[EmitEvent(event=Shutdown(reason='Kontrol penceresi kapandi'))],
    ))
    stop_on_simulator_exit = RegisterEventHandler(OnProcessExit(
        target_action=simulator,
        on_exit=[EmitEvent(event=Shutdown(reason='Turtlesim kapandi'))],
    ))
    return LaunchDescription(arguments + [
        close_all, stop_on_simulator_exit, simulator, controller,
    ])

