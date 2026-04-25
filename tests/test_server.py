import server


def test_main_runs_sse_server(mocker):
    run = mocker.patch.object(server.mcp, "run")

    server.main()

    run.assert_called_once_with(transport="sse", mount_path=server.SERVER_MOUNT_PATH)


def test_main_suppresses_keyboard_interrupt(mocker):
    run = mocker.patch.object(server.mcp, "run", side_effect=KeyboardInterrupt)

    server.main()

    run.assert_called_once_with(transport="sse", mount_path=server.SERVER_MOUNT_PATH)
